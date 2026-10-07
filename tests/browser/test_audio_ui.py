"""Exercise real Web Audio nodes, the jitter buffer, bounded polling, and the live sound control."""
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
        createBiquadFilter() {
          // Every source mixes through this one filter, so tap it to hear what is playing.
          const filter = super.createBiquadFilter()
          this.probe = this.createAnalyser()
          filter.connect(this.probe)
          return filter
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
    if speed > 4.5:
        expect(page.locator('#sound-status')).to_have_text('Sound is off at this speed')
        assert page.evaluate('window.audioContexts[0].latestSource') is None
        state[0] = 'paused'
        expect(page.locator('#sound-status')).to_have_text('Sound paused')
        return
    expect(page.locator('#sound-status')).to_be_hidden()
    page.wait_for_function('''() => {
      const context = window.audioContexts[0]
      const signal = new Float32Array(2048)
      context.probe.getFloatTimeDomainData(signal)
      return context.state === 'running' && signal.some(value => Math.abs(value) > 0.001)
    }''')
    rate = page.evaluate('window.audioContexts[0].latestSource.playbackRate.value')
    # Steady pace holds the playback rate, give or take the small trim that keeps the lead.
    assert rate == pytest.approx(speed, rel=0.025)
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


@pytest.mark.parametrize('mode,low,high', [('watch', 0.3, 1.0), ('manual', 0.05, 0.35)])
def test_sound_lead_follows_control_mode(page, game, mode, low, high):
    url, _, _, _ = game
    calls = []
    pcm = bytes(int(40 + 30 * math.sin(2 * math.pi * frame * 100 / 48000))
                for frame in range(4800) for _ in range(2))
    page.add_init_script('''
      window.leads = []
      const NativeAudioContext = window.AudioContext
      window.AudioContext = class extends NativeAudioContext {
        createBufferSource() {
          const source = super.createBufferSource()
          const start = source.start.bind(source)
          source.start = (when, ...rest) => {
            window.leads.push(when + source.buffer.duration / source.playbackRate.value - this.currentTime)
            return start(when, ...rest)
          }
          return source
        }
      }
    ''')

    def audio(route):
        calls.append(route.request.url)
        route.fulfill(body=pcm, content_type='application/octet-stream', headers={
            'X-Audio-State': 'playing', 'X-Audio-Rate': '48000', 'X-Audio-Mode': mode,
            'X-Audio-Sequence': str(len(calls)), 'X-Audio-Speed': '1',
        })
    page.route('**/api/audio?*', audio)
    page.goto(url)
    page.locator('#sound').click()
    page.wait_for_function('() => window.leads.length > 12')
    leads = page.evaluate('window.leads.slice(-6)')
    assert all(low <= lead <= high for lead in leads), leads
    expect(page.locator('#sound-status')).to_be_hidden()


def test_sound_failure_can_be_retried(page, game):
    url, _, _, _ = game
    page.route('**/api/audio?*', lambda route: route.fulfill(status=503))
    page.goto(url)
    page.locator('#sound').click()
    # A failing connection is retried for a few seconds before the page gives up.
    expect(page.locator('#sound-status')).to_have_text('Audio disconnected. Try again.', timeout=15000)
    expect(page.locator('#sound')).to_have_text('Sound: Off')
    page.locator('#sound').click()
    expect(page.locator('#sound-status')).to_have_text('Audio disconnected. Try again.', timeout=15000)
