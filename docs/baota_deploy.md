# 宝塔面板部署说明

## 1. 上传项目

建议目录：

```text
/www/wwwroot/crawler_project
```

项目根目录应包含：

```text
common/
server/
requirements-server.txt
```

## 2. 创建虚拟环境并安装依赖

在宝塔终端执行：

```bash
cd /www/wwwroot/crawler_project
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-server.txt
```

## 3. 配置环境变量

```bash
cp server/.env.example server/.env
```

编辑：

```bash
vim server/.env
```

至少修改：

```env
DJANGO_SECRET_KEY=换成随机长字符串
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=你的域名.com,服务器IP,127.0.0.1,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://你的域名.com,http://你的域名.com
```

## 4. 初始化数据库和静态文件

```bash
cd /www/wwwroot/crawler_project
source venv/bin/activate
python server/manage.py migrate
python server/manage.py createsuperuser
python server/manage.py collectstatic --noinput
```

如果后台页面没有 CSS，优先检查这一步是否执行成功：

```bash
ls -la /www/wwwroot/crawler_project/server/staticfiles/admin/
```

能看到 `css/`、`js/`、`simpleui-x/` 等目录才正常。

如果不使用 Nginx 静态目录映射，而是让 Django 自己加载静态文件，确保 `server/.env` 中有：

```env
DJANGO_SERVE_STATIC=True
DJANGO_STATIC_URL=/static/
```

## 5. 宝塔 Python 项目启动命令

项目路径：

```text
/www/wwwroot/crawler_project
```

启动命令：

```bash
/www/wwwroot/crawler_project/venv/bin/gunicorn crawler_admin.wsgi:application \
  -c /www/wwwroot/crawler_project/server/gunicorn.conf.py \
  --chdir /www/wwwroot/crawler_project/server
```

默认监听：

```text
127.0.0.1:8000
```

## 6. Nginx 反向代理

宝塔网站配置里反向代理到：

```text
http://127.0.0.1:8000
```

如果你选择让 Django 自己加载 static，可以不添加下面的静态目录规则。

如果后续想改成 Nginx 直接加载静态文件，再添加：

```nginx
location /static/ {
    alias /www/wwwroot/crawler_project/server/staticfiles/;
}

location /media/ {
    alias /www/wwwroot/crawler_project/server/media/;
}
```

项目也内置了 WhiteNoise 兜底静态文件服务，但生产环境仍建议保留上面的 Nginx `/static/` alias，性能更好。

## 7. 客户端 API 地址

客户端连接服务器时设置：

```bash
export CRAWLER_API_BASE=https://你的域名.com/api
```

或在客户端运行环境中配置同名环境变量。
