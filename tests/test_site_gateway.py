import httpx
from fastapi.testclient import TestClient
from backend.site_gateway import create_app


def test_routes_cookies_and_untrusted_proxy_header():
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,headers={'set-cookie':'example=value; Path=/api/reader; HttpOnly'},stream=httpx.ByteStream(b'payload'))
    app=create_app('http://main.internal','http://reader.internal',transport=httpx.MockTransport(respond))
    with TestClient(app) as client:
        response=client.get('/reader/',headers={'x-reader-client-ip':'spoofed'})
        assert response.content==b'payload'
        assert response.headers['set-cookie'].startswith('example=')
        assert calls[-1].url.host=='reader.internal'
        assert calls[-1].headers['x-reader-client-ip']!='spoofed'
        client.post('/api/reader/papers',content=b'pdf')
        assert calls[-1].content==b'pdf'
        client.get('/assets/resource-navigation.html')
        assert calls[-1].url.host=='main.internal'
        client.get('/api/health')
        assert calls[-1].url.host=='main.internal'
