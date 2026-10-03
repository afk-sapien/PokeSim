"""A browser with yesterday's portrait pack must display the migrated artwork."""
from fastapi.responses import HTMLResponse
from PIL import Image

from conftest import serve
from pokesim.web.app import create_app


def test_migrated_portraits_bypass_legacy_cache_and_recheck_replacements(page, game):
    _, store, emu, _ = game
    folder = store.dir / 'sprites'
    folder.mkdir(exist_ok=True)
    portrait = folder / '1.png'
    Image.new('RGB', (56, 56), (255, 0, 0)).save(portrait)
    legacy_requests = []

    def factory(url):
        app = create_app(emu, store, browser_origin=url)

        @app.get('/legacy-portraits')
        def legacy():
            return HTMLResponse('<img src="/sprites/1.png">')

        @app.middleware('http')
        async def legacy_cache(request, call_next):
            response = await call_next(request)
            if request.url.path == '/sprites/1.png' and not request.url.query:
                legacy_requests.append(request.url.path)
                response.headers['Cache-Control'] = 'private, max-age=86400'
            return response

        return app

    def pixel(selector):
        page.wait_for_function('''selector => {
            const image = document.querySelector(selector)
            return image && image.complete && image.naturalWidth === 56
        }''', arg=selector)
        return page.locator(selector).first.evaluate('''image => {
            const canvas = document.createElement('canvas')
            const context = canvas.getContext('2d')
            context.drawImage(image, 0, 0)
            return Array.from(context.getImageData(0, 0, 1, 1).data)
        }''')

    with serve(factory) as url:
        page.goto(url + '/legacy-portraits')
        assert pixel('img') == [255, 0, 0, 255]
        Image.new('RGB', (56, 56), (88, 88, 84)).save(portrait)
        page.goto(url + '/legacy-portraits?visit=2')
        assert pixel('img') == [255, 0, 0, 255]
        assert len(legacy_requests) == 1

        page.goto(url + '/pokedex')
        selector = '.dex-card[data-dex="1"] img'
        assert pixel(selector) == [88, 88, 84, 255]
        assert page.locator(selector).get_attribute('src') != '/sprites/1.png'

        Image.new('RGB', (56, 56), (16, 16, 16)).save(portrait)
        page.goto(url + '/pc?scope=all')
        assert pixel('.pc-mon img') == [16, 16, 16, 255]
