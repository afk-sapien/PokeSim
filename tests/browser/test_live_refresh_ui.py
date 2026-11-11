"""The live page draws its state every 2 seconds and writes nothing to the page that has not changed."""
from test_flows import expect

# Count every write under the page's main column except the game screen, which shows new frames, and the play clock.
WATCH = '''() => {
  window.writes = []
  const moving = (node) => (node.nodeType === 1 ? node : node.parentElement)?.closest('#screen, #playtime')
  new MutationObserver((records) => {
    for (const record of records) {
      if (!moving(record.target)) window.writes.push(`${record.type} ${record.target.id || record.target.parentElement?.id || record.target.nodeName}`)
    }
  }).observe(document.querySelector('main'), {subtree: true, childList: true, attributes: true, characterData: true})
}'''


def refreshes(page, count):
    for _ in range(count):
        with page.expect_response(lambda response: '/api/state' in response.url):
            pass
    # The page draws the answer after it arrives.
    page.wait_for_timeout(300)


def test_an_unchanged_state_leaves_the_page_alone(page, game):
    page.goto(game[0])
    expect(page.locator('#trainer-name')).not_to_have_text('Getting ready')
    expect(page.locator('#badges .lamp')).to_have_count(8)
    # The first draws also load the goal list and the journal once. Let them finish.
    refreshes(page, 1)
    page.evaluate(WATCH)
    refreshes(page, 2)
    assert page.evaluate('window.writes') == []
    # The badge lamps are the same nodes, not a new set drawn over the old one.
    first = page.locator('#badges .lamp').first.element_handle()
    refreshes(page, 1)
    assert page.evaluate('(lamp) => lamp.isConnected', first)
