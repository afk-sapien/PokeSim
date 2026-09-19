"""Check that the actual browser enforces the application content policy."""
from pokesim.app.manager import Manager, create_app
from conftest import serve


def test_library_scripts_work_and_injected_inline_script_is_blocked(page, tmp_path, monkeypatch):
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        return create_app(manager)

    with serve(factory) as url:
        page.goto(url)
        page.locator('#workspace').wait_for(state='visible')
        page.get_by_role('link', name='Settings and backups').click()
        page.locator('#max-running').fill('3')
        page.get_by_role('button', name='Save settings', exact=True).click()
        page.wait_for_function("document.querySelector('#notice').textContent === 'Application settings saved.'")
        violation = page.evaluate("""() => new Promise(resolve => {
            document.addEventListener('securitypolicyviolation', event => resolve(event.violatedDirective), {once: true})
            const script = document.createElement('script')
            script.textContent = 'window.injectedScriptRan = true'
            document.body.appendChild(script)
        })""")
        assert violation == 'script-src-elem'
        assert page.evaluate('window.injectedScriptRan === undefined')
