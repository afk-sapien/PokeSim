"""Exercise real Web Audio nodes, bounded polling, and the live sound control."""
import math

import pytest

from test_flows import expect


@pytest.mark.parametrize('speed', [0.5, 1, 4, 16, 50])
def test_sound_requires_a_click_and_stops_on_mute_and_navigation(page, game, speed):
    url, _, _, _ = game
    calls = []
    state = ['paused']
    pcm = bytes(int(40 + 30 * math.sin(2 * math.pi * frame * 100 / 48000))
                for frame in range(int(4800 * speed)) for _ in range(2))
    page.add_init_script('''
      window.audioContexts = []
      const NativeAudioContext = window.AudioContext
      window.AudioContext = class extends NativeAudioContext {
        constructor(...args) {
          super(...args)
          window.audioContexts.push(this)
        }
        createBufferSource() {
          const source = super.createBufferSource()
          this.latestSource = source
          return source
        }
        createGain() {
          const gain = super.createGain()
          this.probe = this.createAnalyser()
          gain.connect(this.probe)
          return gain
        }
      }
    ''')

    def audio(route):
        calls.append(route.request.url)
        route.fulfill(body=pcm if state[0] == 'playing' else b'',
                      content_type='application/octet-stream', headers={
                          'X-Audio-State': state[0], 'X-Audio-Rate': '48000',
                          'X-Audio-Sequence': str(len(calls)), 'X-Audio-Speed': str(speed),
                      })
    page.route('**/api/audio?*', audio)
    page.goto(url)
    button = page.get_by_role('button', name='Sound: Off', exact=True)
    expect(button).to_be_visible()
    assert calls == []
    button.click()
    expect(page.locator('#sound-status')).to_have_text('Sound paused')
    state[0] = 'playing'
    expect(page.locator('#sound-status')).to_be_hidden()
    page.wait_for_function('''() => {
      const context = window.audioContexts[0]
      const signal = new Float32Array(2048)
      context.probe.getFloatTimeDomainData(signal)
      return context.state === 'running' && signal.some(value => Math.abs(value) > 0.001)
    }''')
    assert page.evaluate('window.audioContexts[0].latestSource.playbackRate.value') == speed
    state[0] = 'paused'
    expect(page.locator('#sound-status')).to_have_text('Sound paused')
    page.get_by_role('button', name='Sound: On', exact=True).click()
    expect(page.locator('#sound')).to_have_attribute('aria-pressed', 'false')
    assert page.evaluate('window.audioContexts[0].state') == 'closed'
    count = len(calls)
    page.wait_for_timeout(350)
    assert len(calls) == count
    page.locator('#sound').click()
    expect(page.locator('#sound')).to_have_attribute('aria-pressed', 'true')
    page.evaluate("window.dispatchEvent(new Event('pagehide'))")
    expect(page.locator('#sound')).to_have_attribute('aria-pressed', 'false')
    assert page.evaluate('window.audioContexts[1].state') == 'closed'


def test_sound_failure_can_be_retried(page, game):
    url, _, _, _ = game
    page.route('**/api/audio?*', lambda route: route.fulfill(status=503))
    page.goto(url)
    page.locator('#sound').click()
    expect(page.locator('#sound-status')).to_have_text('Audio disconnected. Try again.')
    expect(page.locator('#sound')).to_have_text('Sound: Off')
    page.locator('#sound').click()
    expect(page.locator('#sound-status')).to_have_text('Audio disconnected. Try again.')
