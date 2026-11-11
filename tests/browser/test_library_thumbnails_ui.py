"""Library card pictures follow the game without going blank."""
import io

from PIL import Image

from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier
from conftest import serve


def expect(locator):
    from playwright.sync_api import expect as assertion
    return assertion(locator)


def frame(color):
    image = io.BytesIO()
    Image.new('RGB', (160, 144), color).save(image, 'JPEG')
    return image.getvalue()


# Each time the card list changes, every card picture must already be drawn, and once a new
# frame has arrived no picture may fall back to the one the page first loaded.
WATCH = """() => {
  window.thumbs = {blank: 0, reverted: 0, swapped: false}
  const check = () => {
    for (const img of document.querySelectorAll('#adventure-list .card-screen img')) {
      if (!img.complete || !img.naturalWidth) window.thumbs.blank += 1
      if (img.src.includes('?at=')) window.thumbs.swapped = true
      else if (window.thumbs.swapped) window.thumbs.reverted += 1
    }
  }
  new MutationObserver(check).observe(document.querySelector('#adventure-list'), {childList: true, subtree: true})
}"""


def test_running_cards_show_new_frames_in_place(page, tmp_path, monkeypatch):
    built = {}

    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        monkeypatch.setattr(manager.supervisor, 'resources', lambda aid: {})
        manager.registry.add_rom('fixture', 'sha1', 'blue')
        row = manager.registry.create('Blue', 'fixture', {}, identifier())
        manager.registry.transition(row['id'], 'running', 'test setup', summary={'activity': 'Route 24'})
        built.update(manager=manager, id=row['id'])
        return create_app(manager)

    colors = ['#99aa77', '#336699', '#aa3344', '#dddd22']
    asked = []

    def answer(route):
        asked.append(route.request.url)
        route.fulfill(body=frame(colors[min(len(asked), len(colors)) - 1]), content_type='image/jpeg')

    page.route('**/frame.jpg*', answer)
    with serve(factory) as url:
        page.goto(url)
        page.wait_for_function("() => { const img = document.querySelector('.card-screen img'); return img?.complete && img.naturalWidth > 0 }")
        page.evaluate(WATCH)
        # The library's 3 second refresh asks for a new frame and swaps it in once it is drawn.
        page.wait_for_function('() => window.thumbs.swapped', timeout=10000)
        assert any('?at=' in request for request in asked)
        # A changed summary redraws the card. It keeps the newer picture.
        built['manager'].registry.update(built['id'], summary={'activity': 'Cerulean Cave'})
        expect(page.locator('.adventure-card')).to_contain_text('Cerulean Cave')
        expect(page.locator('.card-screen img')).to_have_count(1)
        assert page.evaluate('() => window.thumbs') == {'blank': 0, 'reverted': 0, 'swapped': True}
