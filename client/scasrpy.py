from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from DrissionPage import Chromium, ChromiumOptions
except Exception:
    Chromium = None
    ChromiumOptions = None


from common.project_settings import DEFAULT_BROWSER_PATH


def clean_text(value: Any) -> str:
    if value is None:
        return ''
    text = html.unescape(str(value))
    return re.sub(r'\s+', ' ', text).strip()


def normalize_url(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ''
    if value.startswith('//'):
        return f'https:{value}'
    if value.startswith('http://') or value.startswith('https://'):
        return value
    return value


def unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def clean_product_title(value: Any) -> str:
    return re.sub(r'\s*[-_]?淘宝网.*$', '', clean_text(value)).strip()


def parse_json_fragment(raw: str) -> Any:
    raw = html.unescape(raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(raw.encode('utf-8').decode('unicode_escape'))
    except Exception:
        return None


def find_balanced_json(text: str, start: int) -> str:
    opening = text[start]
    closing = '}' if opening == '{' else ']'
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return ''


def walk_json(value: Any):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_json(item)


def strip_tags(fragment: str) -> str:
    fragment = re.sub(r'<(?:script|style)[^>]*>.*?</(?:script|style)>', ' ', fragment, flags=re.S | re.I)
    fragment = re.sub(r'<br\s*/?>', '\n', fragment, flags=re.I)
    fragment = re.sub(r'</(?:div|p|li|span|button|a|dt|dd|tr|td|th)>', '\n', fragment, flags=re.I)
    fragment = re.sub(r'<[^>]+>', ' ', fragment)
    return html.unescape(fragment)


@dataclass
class TaobaoProductParser:
    url: str
    html_text: str
    title: str = ''
    json_blocks: list[Any] = field(default_factory=list)

    def parse(self) -> dict[str, Any]:
        self.json_blocks = self.extract_json_blocks()
        item_id = self.extract_item_id()
        product = {
            'platform': 'taobao',
            'item_id': item_id,
            'url': self.url,
            'page_title': clean_text(self.title),
            'title': self.extract_title(),
            'price': self.extract_price(),
            'sales': self.extract_sales(),
            'images': self.extract_images(),
            'shop': self.extract_shop(),
            'sku': self.extract_sku(),
            'specifications': self.extract_specifications(),
            'parameters': self.extract_parameters(),
            'properties': self.extract_properties(),
            'raw_blocks_found': len(self.json_blocks),
            'fetched_at': int(time.time()),
        }
        product['missing_fields'] = [key for key, value in product.items() if value in ('', [], {})]
        return product

    def extract_json_blocks(self) -> list[Any]:
        blocks: list[Any] = []

        for pattern in (
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            r'<script[^>]+id=["\']ice-container-data["\'][^>]*>(.*?)</script>',
        ):
            for match in re.finditer(pattern, self.html_text, re.S | re.I):
                parsed = parse_json_fragment(match.group(1))
                if parsed is not None:
                    blocks.append(parsed)

        for token in ('window.__INIT_DATA__', '__INIT_DATA__', '__WPO_DATA__', 'g_config'):
            for match in re.finditer(re.escape(token), self.html_text):
                start = self.html_text.find('{', match.end())
                if start == -1:
                    continue
                fragment = find_balanced_json(self.html_text, start)
                parsed = parse_json_fragment(fragment) if fragment else None
                if parsed is not None:
                    blocks.append(parsed)

        return blocks

    def extract_item_id(self) -> str:
        query = parse_qs(urlparse(self.url).query)
        if query.get('id'):
            return query['id'][0]
        match = re.search(r'"(?:itemId|item_id|auctionId)"\s*:\s*"?(\d+)"?', self.html_text)
        return match.group(1) if match else ''

    def extract_title(self) -> str:
        candidates = []
        for node in walk_json(self.json_blocks):
            if isinstance(node, dict):
                for key in ('title', 'itemTitle', 'rawTitle', 'name', 'goodsName'):
                    value = node.get(key)
                    if isinstance(value, str) and len(clean_text(value)) > 3:
                        candidates.append(clean_product_title(value))
        candidates.extend(clean_product_title(item) for item in self.extract_meta_values(('og:title', 'twitter:title')))
        candidates.append(clean_product_title(self.title))
        return self.best_text(candidates)

    def extract_price(self) -> dict[str, Any]:
        prices: list[str] = []
        currency = ''
        for node in walk_json(self.json_blocks):
            if isinstance(node, dict):
                for key in ('price', 'priceText', 'priceValue', 'promotionPrice', 'salePrice', 'reservePrice'):
                    value = node.get(key)
                    if isinstance(value, (str, int, float)):
                        text = clean_text(value)
                        if re.search(r'\d', text):
                            prices.append(text)
                if not currency and isinstance(node.get('priceCurrency'), str):
                    currency = node['priceCurrency']

        for match in re.finditer(r'"(?:price|priceText|promotionPrice|salePrice)"\s*:\s*"([^"]+)"', self.html_text):
            prices.append(clean_text(match.group(1)))

        prices = unique([p for p in prices if len(p) <= 40])
        return {'currency': currency or 'CNY', 'values': prices}

    def extract_sales(self) -> dict[str, str]:
        result = {}
        for node in walk_json(self.json_blocks):
            if isinstance(node, dict):
                for key in ('soldCount', 'sellCount', 'sales', 'monthSellCount', 'totalSoldQuantity'):
                    value = node.get(key)
                    if value not in (None, ''):
                        result[key] = clean_text(value)
        if not result:
            match = re.search(r'月销\s*([0-9.万wW+]+)', self.html_text)
            if match:
                result['month_sales'] = match.group(1)
        return result

    def extract_images(self) -> list[str]:
        images: list[str] = []
        for node in walk_json(self.json_blocks):
            if isinstance(node, dict):
                for key in ('image', 'images', 'picUrl', 'pic_url', 'mainPic', 'img', 'url'):
                    value = node.get(key)
                    images.extend(self.collect_urls(value))
            elif isinstance(node, str):
                images.extend(self.collect_urls(node))

        for match in re.finditer(r'(?:https?:)?//[^"\']+\.(?:jpg|jpeg|png|webp)(?:_[^"\']*)?', self.html_text, re.I):
            images.append(normalize_url(match.group(0)))

        return unique([img for img in images if 'alicdn.com' in img or 'taobao' in img])[:80]

    def extract_shop(self) -> dict[str, str]:
        shop = {}
        for node in walk_json(self.json_blocks):
            if not isinstance(node, dict):
                continue
            for key, target in (
                ('shopName', 'name'),
                ('sellerNick', 'seller_nick'),
                ('sellerId', 'seller_id'),
                ('shopId', 'shop_id'),
                ('shopUrl', 'url'),
                ('shopIcon', 'icon'),
            ):
                value = node.get(key)
                if value and target not in shop:
                    shop[target] = normalize_url(str(value)) if target in ('url', 'icon') else clean_text(value)
        return shop

    def extract_sku(self) -> list[dict[str, Any]]:
        skus = self.extract_sku_from_models()
        if skus:
            return skus[:200]

        skus: list[dict[str, Any]] = []
        for node in walk_json(self.json_blocks):
            if not isinstance(node, dict):
                continue
            if any(key in node for key in ('skuId', 'sku_id')) and any(key in node for key in ('price', 'priceText', 'stock', 'quantity')):
                skus.append({
                    'sku_id': clean_text(node.get('skuId') or node.get('sku_id')),
                    'name': clean_text(node.get('name') or node.get('title') or node.get('propPath') or node.get('propertiesName')),
                    'price': clean_text(node.get('price') or node.get('priceText') or node.get('promotionPrice')),
                    'stock': clean_text(node.get('stock') or node.get('quantity') or node.get('inventory')),
                    'prop_path': clean_text(node.get('propPath') or node.get('prop_path')),
                    'specs': {},
                })
        return [sku for sku in skus if any(sku.values())][:100]

    def extract_sku_from_models(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        sku_value_map = self.build_sku_value_map()

        for node in walk_json(self.json_blocks):
            if not isinstance(node, dict):
                continue
            sku2info = node.get('sku2info') or node.get('sku2Info') or node.get('skuMap')
            if not isinstance(sku2info, dict):
                continue
            for sku_id, info in sku2info.items():
                if not isinstance(info, dict):
                    continue
                prop_path = clean_text(info.get('propPath') or info.get('properties') or info.get('pvPath'))
                specs = self.resolve_prop_path(prop_path, sku_value_map)
                price = self.first_value(info, ('priceText', 'price', 'promotionPrice', 'salePrice'))
                quantity = self.first_value(info, ('quantity', 'stock', 'inventory', 'stockNum'))
                result.append({
                    'sku_id': clean_text(info.get('skuId') or info.get('sku_id') or sku_id),
                    'name': ' '.join(specs.values()) if specs else clean_text(info.get('name') or info.get('title')),
                    'price': clean_text(price),
                    'stock': clean_text(quantity),
                    'prop_path': prop_path,
                    'specs': specs,
                })

        return self.unique_dicts(result, ('sku_id', 'prop_path'))

    def extract_specifications(self) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = self.extract_dom_specifications()
        seen = set()
        for spec in specs:
            seen.add((spec.get('id', ''), spec.get('name', '')))
        for node in walk_json(self.json_blocks):
            if not isinstance(node, dict):
                continue
            props = node.get('props') or node.get('saleProps') or node.get('skuProps')
            if not isinstance(props, list):
                continue
            for prop in props:
                if not isinstance(prop, dict):
                    continue
                prop_id = clean_text(prop.get('pid') or prop.get('propId') or prop.get('id'))
                prop_name = clean_text(prop.get('name') or prop.get('propName') or prop.get('text'))
                values = self.extract_spec_values(prop)
                key = (prop_id, prop_name)
                if prop_name and values and key not in seen:
                    seen.add(key)
                    specs.append({'id': prop_id, 'name': prop_name, 'values': values})
        return specs[:50]

    def extract_dom_specifications(self) -> list[dict[str, Any]]:
        block = self.extract_block_by_class_prefix('contentWrap--')
        if not block:
            return []

        lines = self.extract_visible_lines(block)
        specs: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        spec_names = ('颜色', '颜色分类', '尺码', '尺寸', '规格', '款式', '套餐', '版本', '容量', '净含量', '型号', '数量', '分类')

        for line in lines:
            label = line.rstrip(':：')
            is_name = line.endswith((':', '：')) or label in spec_names or any(label.endswith(name) for name in spec_names)
            if is_name:
                current = {'id': '', 'name': label, 'values': []}
                specs.append(current)
                continue
            if current and line != current['name']:
                current['values'].append({'id': '', 'name': line, 'image': ''})

        if specs:
            return self.normalize_specs(specs)

        option_texts = self.extract_option_texts(block)
        if option_texts:
            return [{'id': '', 'name': '规格', 'values': [{'id': '', 'name': item, 'image': ''} for item in option_texts]}]
        return []

    def extract_spec_values(self, prop: dict[str, Any]) -> list[dict[str, str]]:
        raw_values = prop.get('values') or prop.get('valueList') or prop.get('children') or prop.get('items')
        if not isinstance(raw_values, list):
            return []
        values = []
        seen = set()
        for item in raw_values:
            if not isinstance(item, dict):
                continue
            value_id = clean_text(item.get('vid') or item.get('valueId') or item.get('id'))
            name = clean_text(item.get('name') or item.get('value') or item.get('text'))
            image = normalize_url(str(item.get('image') or item.get('imgUrl') or item.get('picUrl') or ''))
            key = (value_id, name)
            if name and key not in seen:
                seen.add(key)
                values.append({'id': value_id, 'name': name, 'image': image})
        return values

    def extract_parameters(self) -> list[dict[str, str]]:
        params: list[dict[str, str]] = self.extract_dom_parameters()
        for node in walk_json(self.json_blocks):
            if not isinstance(node, dict):
                continue
            for key in ('groupProps', 'propsList', 'paramList', 'basicProps', 'attributes'):
                params.extend(self.parse_parameter_block(node.get(key)))
            params.extend(self.parse_parameter_pair(node))
        return self.unique_dicts(params, ('name', 'value'))[:200]

    def extract_dom_parameters(self) -> list[dict[str, str]]:
        block = self.extract_block_by_class_prefix('paramsInfoArea')
        if not block:
            return []

        params = []
        lines = self.extract_visible_lines(block)
        for line in lines:
            params.extend(self.parse_parameter_text(line))
        for index in range(0, len(lines) - 1, 2):
            item = self.make_parameter(lines[index], lines[index + 1])
            if item:
                params.append(item)
        return self.unique_dicts(params, ('name', 'value'))

    def extract_properties(self) -> dict[str, str]:
        props = {item['name']: item['value'] for item in self.extract_parameters()}
        return props

    def parse_parameter_block(self, value: Any) -> list[dict[str, str]]:
        params: list[dict[str, str]] = []
        if isinstance(value, list):
            for item in value:
                params.extend(self.parse_parameter_block(item))
        elif isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, (str, int, float)):
                    params.append(self.make_parameter(key, item))
                else:
                    params.extend(self.parse_parameter_block(item))
            params.extend(self.parse_parameter_pair(value))
        elif isinstance(value, str):
            params.extend(self.parse_parameter_text(value))
        return [item for item in params if item]

    def parse_parameter_pair(self, node: dict[str, Any]) -> list[dict[str, str]]:
        name = node.get('name') or node.get('key') or node.get('propName') or node.get('attrName') or node.get('title')
        value = node.get('value') or node.get('text') or node.get('propValue') or node.get('attrValue') or node.get('desc')
        item = self.make_parameter(name, value)
        return [item] if item else []

    def parse_parameter_text(self, value: str) -> list[dict[str, str]]:
        params = []
        for name, text in re.findall(r'([^:：;；\n]{1,40})[:：]\s*([^;；\n]{1,200})', clean_text(value)):
            item = self.make_parameter(name, text)
            if item:
                params.append(item)
        return params

    def make_parameter(self, name: Any, value: Any) -> dict[str, str]:
        name = clean_text(name)
        value = clean_text(value)
        if not name or not value:
            return {}
        if len(name) > 50 or len(value) > 300:
            return {}
        if name in ('url', 'image', 'images', 'picUrl', 'traceId', 'spm'):
            return {}
        return {'name': name, 'value': value}

    def build_sku_value_map(self) -> dict[str, tuple[str, str]]:
        mapping: dict[str, tuple[str, str]] = {}
        for spec in self.extract_specifications():
            prop_id = spec.get('id') or ''
            prop_name = spec.get('name') or ''
            for value in spec.get('values', []):
                value_id = value.get('id') or ''
                value_name = value.get('name') or ''
                if prop_id and value_id:
                    mapping[f'{prop_id}:{value_id}'] = (prop_name, value_name)
                if value_id:
                    mapping[value_id] = (prop_name, value_name)
        return mapping

    def resolve_prop_path(self, prop_path: str, sku_value_map: dict[str, tuple[str, str]]) -> dict[str, str]:
        specs: dict[str, str] = {}
        for part in re.split(r'[;,]', prop_path):
            part = clean_text(part)
            if not part:
                continue
            prop_name, value_name = sku_value_map.get(part, ('', ''))
            if not value_name and ':' in part:
                prop_id, value_id = part.split(':', 1)
                prop_name, value_name = sku_value_map.get(value_id, (prop_id, value_id))
            if value_name:
                specs[prop_name or part] = value_name
        return specs

    def first_value(self, node: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = node.get(key)
            if value not in (None, ''):
                return value
        return ''

    def unique_dicts(self, items: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
        seen = set()
        result = []
        for item in items:
            marker = tuple(clean_text(item.get(key)) for key in keys)
            if not any(marker) or marker in seen:
                continue
            seen.add(marker)
            result.append(item)
        return result

    def extract_block_by_class_prefix(self, class_prefix: str) -> str:
        pattern = rf'<(?P<tag>[a-zA-Z0-9]+)\b[^>]*class=["\'][^"\']*{re.escape(class_prefix)}[^"\']*["\'][^>]*>'
        match = re.search(pattern, self.html_text, re.I)
        if not match:
            return ''
        tag = match.group('tag').lower()
        start = match.start()
        depth = 0
        tag_pattern = re.compile(rf'</?{re.escape(tag)}\b[^>]*>', re.I)
        for item in tag_pattern.finditer(self.html_text, start):
            if item.group(0).startswith('</'):
                depth -= 1
                if depth == 0:
                    return self.html_text[start:item.end()]
            else:
                depth += 1
        return self.html_text[start:start + 20000]

    def extract_visible_lines(self, fragment: str) -> list[str]:
        text = strip_tags(fragment)
        lines = []
        for line in re.split(r'[\n\r]+', text):
            line = clean_text(line)
            if not line:
                continue
            if line in ('请选择', '已选', '购买数量', '加入购物车', '立即购买'):
                continue
            if len(line) <= 80:
                lines.append(line)
        return unique(lines)

    def extract_option_texts(self, fragment: str) -> list[str]:
        values = []
        for attr in ('title', 'aria-label', 'alt'):
            for match in re.finditer(rf'\b{attr}=["\']([^"\']+)["\']', fragment, re.I):
                value = clean_text(match.group(1))
                if value and len(value) <= 80:
                    values.append(value)
        values.extend(self.extract_visible_lines(fragment))
        return unique(values)

    def normalize_specs(self, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for spec in specs:
            values = self.unique_dicts(spec.get('values', []), ('name',))
            values = [item for item in values if item.get('name') and item.get('name') != spec.get('name')]
            if spec.get('name') and values:
                normalized.append({'id': spec.get('id', ''), 'name': spec['name'], 'values': values})
        return normalized

    def extract_meta_values(self, names: tuple[str, ...]) -> list[str]:
        values = []
        for name in names:
            pattern = rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']'
            values.extend(clean_text(match.group(1)) for match in re.finditer(pattern, self.html_text, re.I))
        return values

    def collect_urls(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [normalize_url(item) for item in re.findall(r'(?:https?:)?//[^,\s"\']+', value)]
        if isinstance(value, list):
            urls = []
            for item in value:
                urls.extend(self.collect_urls(item))
            return urls
        if isinstance(value, dict):
            urls = []
            for item in value.values():
                urls.extend(self.collect_urls(item))
            return urls
        return []

    def best_text(self, candidates: list[str]) -> str:
        candidates = [clean_text(item) for item in candidates if clean_text(item)]
        if not candidates:
            return ''
        return max(unique(candidates), key=len)


def is_login_or_risk_page(title: str, current_url: str, html_text: str) -> bool:
    """只识别明确的登录/风控页，避免正常商品页 HTML 中出现 _lgt_ 造成误判。"""
    title = title or ''
    current_url = current_url or ''
    html_text = html_text or ''
    url_or_title = f'{current_url}\n{title}'
    if title in ('登入', '登录'):
        return True
    if any(marker in url_or_title for marker in ('login.taobao.com', 'login_jump', '_____tmd_____')):
        return True
    return any(marker in html_text for marker in (
        'login.taobao.com/member/login.jhtml',
        '请登录',
        '扫码登录',
        '密码登录',
        'login-form',
        'fm-login-id',
    ))


def fetch_product(page, url: str) -> dict[str, Any]:
    page.get(url)
    page.wait.doc_loaded()
    title = clean_text(page.title)
    current_url = clean_text(getattr(page, 'url', ''))
    html = getattr(page, 'html', '') or ''

    if is_login_or_risk_page(title, current_url, html):
        return {
            'platform': 'taobao',
            'url': url,
            'current_url': current_url,
            'page_title': title,
            'login_required': True,
            'error': '需要登录淘宝账号后再获取',
            'fetched_at': int(time.time()),
        }

    parser = TaobaoProductParser(url=url, html_text=html, title=title)
    data = parser.parse()
    data['current_url'] = current_url
    data['login_required'] = False
    return data


def get_comments(page, url: str) -> dict[str, Any]:
    return fetch_product(page, url)


def get_commnets(page, url: str) -> dict[str, Any]:
    # 保留原函数名，避免旧代码调用拼写错误的方法时报错。
    return get_comments(page, url)


def build_page(browser_path: str = DEFAULT_BROWSER_PATH, headless: bool = False):
    if Chromium is None or ChromiumOptions is None:
        raise RuntimeError('DrissionPage 未安装，请先 pip install -r requirements.txt')
    options = ChromiumOptions().set_browser_path(browser_path)
    if headless:
        options.headless(True)
    tab = Chromium(options)
    return tab.get_tab()


def main() -> None:
    parser = argparse.ArgumentParser(description='Taobao product crawler client')
    parser.add_argument('url', nargs='?', default='https://item.taobao.com/item.htm?id=975460280575')
    parser.add_argument('--browser-path', default=DEFAULT_BROWSER_PATH)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--output', default='')
    args = parser.parse_args()

    page = build_page(args.browser_path, args.headless)
    data = fetch_product(page, args.url)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload, encoding='utf-8')
    print(payload)


if __name__ == '__main__':
    main()
