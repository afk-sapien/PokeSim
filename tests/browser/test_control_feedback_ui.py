"""A control button says at once what it is doing while the game finishes its current step, and the
state redraws in between leave that label alone."""
import time

from fastapi import HTTPException

from conftest import refused
from test_flows import expect

# When the click arrives, and the button's first label after it.
WATCH = '''() => {
  const take = document.getElementById('take-control')
  window.feedback = {}
  document.addEventListener('click', () => { window.feedback.click = performance.now() }, true)
  new MutationObserver(() => {
    if (window.feedback.click !== undefined && !window.feedback.label) {
      window.feedback.label = {after: performance.now() - window.feedback.click, text: take.textContent}
    }
  }).observe(take, {childList: true, characterData: true, subtree: true})
}'''


def test_take_control_says_so_while_the_game_finishes_its_step(page, game):
    url, _, emu, _ = game
    status, taken = emu.status, []

    def command(name, value=None):
        if name == 'take_control':
            # Longer than the page's 2 second state poll, so a redraw lands while the game is busy.
            time.sleep(3)
            taken.append(name)
        emu.commands.append((name, value))

    emu.command = command
    emu.status = lambda: {**status(), 'manual_mode': bool(taken), 'paused': bool(taken)}
    page.goto(url)
    take = page.locator('#take-control')
    expect(page.locator('#trainer-name')).not_to_have_text('Getting ready')
    expect(take).to_have_text('Take control')
    page.evaluate(WATCH)
    take.click()
    label = page.evaluate('window.feedback.label')
    assert label['text'] == 'Taking control…' and label['after'] < 100, label
    expect(take).to_have_attribute('aria-busy', 'true')
    # It reads as working, not as a refused button.
    assert page.evaluate("getComputedStyle(document.getElementById('take-control')).cursor") == 'progress'
    with page.expect_response(lambda response: '/api/state' in response.url):
        pass
    page.wait_for_timeout(100)
    assert not taken, 'The state poll did not land while the game was busy'
    expect(take).to_have_text('Taking control…')
    # The game answers: the button names what it does now.
    expect(take).to_have_text('Let AI play', timeout=6000)
    expect(take).not_to_have_attribute('aria-busy', 'true')
    expect(take).to_be_enabled()
    expect(page.locator('#status')).to_have_text('In control')


def test_a_refused_control_puts_the_label_back(page, game, expected_errors):
    url, _, emu, _ = game
    expected_errors(*refused('/api/control', 409))

    def command(name, value=None):
        time.sleep(0.3)
        raise HTTPException(409, 'Refused for this scenario')

    emu.command = command
    page.goto(url)
    pause = page.locator('#pause')
    expect(page.locator('#trainer-name')).not_to_have_text('Getting ready')
    expect(pause).to_have_text('Pause')
    pause.click()
    expect(pause).to_have_text('Pausing…')
    expect(pause).to_have_text('Pause')
    expect(pause).to_be_enabled()
    expect(pause).not_to_have_attribute('aria-busy', 'true')
