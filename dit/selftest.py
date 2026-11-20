"""Task-system self-test (part of `python main.py --test`) and the on-screen card demo (`--demo-ui`)."""
import math
import os
import tempfile
import time

from .config import Config
from .env import get_secret


def run_task_self_test(config: Config, feedback) -> int:
    """Exercises the task pipeline end to end against throwaway databases. Returns the failure count."""
    from .tasks.intents import parse_rules
    from .tasks.models import COMPLETED, ACTIVE, PAUSED
    from .tasks.store import TaskStore
    from .tasks.manager import TaskManager
    from .tasks import manager as manager_mod
    from .watch.context import build_context
    from .watch.window import WindowInfo, foreground_window, idle_seconds
    from .watch.sessionizer import Sessionizer

    failures = 0
    tmp = tempfile.mkdtemp(prefix="dictateit-test-")

    print("[4/7] Testing task store + rule-based intents...")
    store = TaskStore(os.path.join(tmp, "test.db"))
    t1 = store.add_task("Finish November financial report", "Financial reporting")
    t2 = store.add_task("Fix OAuth redirect bug", "Billing")
    tasks = store.open_tasks()
    cases = [
        ("Add a task to email Sarah the Q3 numbers", "add", None, None),
        ("Finish the November financial report", "add", None, None),
        ("I'm done with the report", "complete", t1.id, None),
        ("remove the oauth bug", "remove", t2.id, None),
        ("pause the report", "pause", t1.id, None),
        ("what's next", "peek", None, None),
        ("yeah that's done", "complete", t2.id, t2.id),
        ("not yet", "pause", t2.id, t2.id),
        ("this is urgent, call the bank about the card", "add", None, None),
    ]
    for text, action, tid, pending in cases:
        it = parse_rules(text, tasks, pending_id=pending)
        ok = it.action == action and (tid is None or it.task_id == tid)
        failures += 0 if ok else 1
        extra = f"#{it.task_id}" if it.task_id else f"{it.title!r} [{it.priority}]" if it.title else ""
        print(f"  {'✓' if ok else '✗'} \"{text}\" -> {it.action} {extra}")
    # Regression: real phrases from 2026-11-18 that failed (unmatched "done", or turned into new tasks).
    dp1 = store.add_task("Check DP World EIRs and Debolyly port EIR")
    acct = store.add_task("Activate Absolomonon's account")
    gda = store.add_task("GDA6 automation")
    real = store.open_tasks()
    regress = [
        ("DP World done.", "complete", dp1.id), ("TP World EIRs checked and done", "complete", dp1.id),
        ("account is fixed.", "complete", acct.id), ("GDS6 is done, automation part I mean.", "complete", gda.id),
        ("I was done with the account damage while you keep making new tasks.", "complete", acct.id),
        ("Last task was completed", "complete", gda.id), ("make sure the report is done by Friday", "add", None),
    ]
    for text, action, tid in regress:
        it = parse_rules(text, real, None, None, gda.id)
        ok = it.action == action and (tid is None or it.task_id == tid)
        failures += 0 if ok else 1
        print(f"  {'✓' if ok else '✗'} \"{text[:48]}\" -> {it.action} {('#' + str(it.task_id)) if it.task_id else it.title or ''}")
    for t in (dp1, acct, gda):
        store.set_status(t.id, COMPLETED)
    store.set_status(t1.id, ACTIVE)
    store.set_status(t2.id, ACTIVE)
    paused_ok = store.get_task(t1.id).status == PAUSED
    failures += 0 if paused_ok else 1
    store.set_status(t2.id, COMPLETED)
    print(f"  {'✓' if paused_ok else '✗'} Activating a task pauses the previous one; "
          f"queue: {[t.title for t in store.open_tasks()]}")

    print("[5/7] Testing window-title context parsing...")
    samples = [
        ("chrome.exe", "Nov Report - Google Sheets - Google Chrome", "Nov Report - Google Sheets", None),
        ("code.exe", "● engine.py - D^it - Visual Studio Code", "engine.py - D^it", "D^it"),
        ("msedge.exe", "(3) Inbox - Outlook and 2 more pages - Personal - Microsoft​ Edge", "Inbox - Outlook", None),
        ("chrome.exe", "New Incognito Tab - Google Chrome", "Private window", None),
        ("excel.exe", "November_financials.xlsx - Excel", "November_financials.xlsx", None),
    ]
    for exe, title, want_label, want_ws in samples:
        ctx = build_context(WindowInfo(0, 0, exe, "", title, ""), config.private_apps)
        ok = ctx.label == want_label and ctx.workspace == want_ws
        failures += 0 if ok else 1
        print(f"  {'✓' if ok else '✗'} {ctx.app:<8} \"{title[:40]}\" -> label={ctx.label!r} ws={ctx.workspace!r}"
              f"{' (private: never linked or sent)' if ctx.private else ''}")
    from .watch.browser import clean_url, BrowserUrlReader
    url_cases = [
        ("https://docs.google.com/spreadsheets/d/1AbC/edit?gid=0#gid=0", "https://docs.google.com/spreadsheets/d/1AbC/edit"),
        ("github.com/acme/billing/pull/42", "https://github.com/acme/billing/pull/42"),
        ("mail.google.com/mail/u/0/?token=SECRET#inbox", "https://mail.google.com/mail/u/0"),
        ("how to fix oauth redirect", None),
        ("edge://settings/privacy", None),
    ]
    for raw, want in url_cases:
        got = clean_url(raw)
        ok = got == want
        failures += 0 if ok else 1
        print(f"  {'✓' if ok else '✗'} URL {raw[:44]!r} -> {got}")
    sheet = build_context(WindowInfo(0, 0, "chrome.exe", "", "Nov Report - Google Sheets - Google Chrome", ""),
                          config.private_apps, "https://docs.google.com/spreadsheets/d/1AbC/edit")
    ok = sheet.key == "chrome::docs.google.com/spreadsheets/d/1abc/edit" and sheet.site == "docs.google.com"
    failures += 0 if ok else 1
    print(f"  {'✓' if ok else '✗'} Browser context keyed by page: {sheet.key} | describe={sheet.describe()!r}")
    win = foreground_window()
    live_url = None
    if win and win.exe in ("chrome.exe", "msedge.exe", "brave.exe", "firefox.exe"):
        tab = BrowserUrlReader().read(win.hwnd, win.exe)
        live_url = tab.url if tab else None
    print(f"  ✓ Live foreground window: {win.exe if win else None} | idle {idle_seconds():.1f}s"
          f"{f' | tab site: {build_context(win, (), live_url).site}' if live_url else ''}")

    print("[6/7] Simulating: report in Google Sheets -> switch to VS Code -> 'wrapped up?' nudge...")

    class FakeUI:
        def __init__(self):
            self.shown = []

        def show(self, content, card_id=None, payload=None, level_fn=None):
            self.shown.append(content)
            return card_id or len(self.shown)

        def dismiss(self, *a, **k):
            pass

        def is_showing(self, card_id):
            return False

    sim_cfg = Config(**{**config.__dict__, "settle_s": 2, "activate_after_s": 5, "nudge_after_s": 30,
                        "nudge_min_focus_s": 20, "nudge_cooldown_s": 0})
    store2 = TaskStore(os.path.join(tmp, "sim.db"))
    report = store2.add_task("Finish November financial report", "Financial reporting")
    fake_ui = FakeUI()
    mgr = TaskManager(sim_cfg, store2, fake_ui, feedback, ai_client=None)
    sess = Sessionizer(sim_cfg.settle_s, sim_cfg.idle_after_s, mgr.on_segment_start, mgr.on_segment_end, mgr.on_tick)
    real_welcome = manager_mod.notifications_welcome
    manager_mod.notifications_welcome = lambda: True
    try:
        sheets = build_context(WindowInfo(0, 0, "chrome.exe", "", "November Report - Google Sheets - Google Chrome", ""))
        vscode = build_context(WindowInfo(0, 0, "code.exe", "", "engine.py - D^it - Visual Studio Code", ""))
        t0 = 1_000_000.0
        for i in range(60):
            sess.tick(sheets, 0, t0 + i)
        status_mid = store2.get_task(report.id).status
        for i in range(3):
            sess.tick(sheets, 0, t0 + 60 + i)           # Alt-Tab blip below settle time: no switch
        for i in range(63, 130):
            sess.tick(vscode, 0, t0 + i)
    finally:
        manager_mod.notifications_welcome = real_welcome
    kinds = [c.kind for c in fake_ui.shown]
    final = store2.get_task(report.id)
    ok = status_mid == ACTIVE and kinds.count("nudge") == 1 and final.status != COMPLETED
    failures += 0 if ok else 1
    print(f"  {'✓' if ok else '✗'} In Sheets -> {status_mid}; after VS Code: cards={kinds}, "
          f"status={final.status} (never auto-completed)")
    nudge_card = kinds.index("nudge") + 1
    mgr.on_card_action(nudge_card, "done", report.id)
    done_ok = store2.get_task(report.id).status == COMPLETED and fake_ui.shown[-1].kind == "done"
    failures += 0 if done_ok else 1
    print(f"  {'✓' if done_ok else '✗'} Clicking 'Done' on the nudge -> {store2.get_task(report.id).status}")

    print("      ...and with nothing linked and no AI: check-in, then nudge")
    store3 = TaskStore(os.path.join(tmp, "sim2.db"))
    eir = store3.add_task("Check DP World EIRs")
    ui3 = FakeUI()
    cfg3 = Config(**{**sim_cfg.__dict__, "checkin_after_s": 20, "checkin_cooldown_s": 0})
    mgr3 = TaskManager(cfg3, store3, ui3, feedback, ai_client=None)
    sess3 = Sessionizer(cfg3.settle_s, cfg3.idle_after_s, mgr3.on_segment_start, mgr3.on_segment_end, mgr3.on_tick)
    manager_mod.notifications_welcome = lambda: True
    try:
        portal = build_context(WindowInfo(0, 0, "msedge.exe", "", "Ibras95", ""), (), "https://portal.example.com/eir",
                               "Container status - Portal")
        whatsapp = build_context(WindowInfo(0, 0, "whatsapp.root.exe", "", "WhatsApp", ""))
        t0 = 2_000_000.0
        for i in range(30):
            sess3.tick(portal, 0, t0 + i)
        checkin_shown = any(c.eyebrow == "Working on this?" for c in ui3.shown)
        mgr3.on_card_action(mgr3._checkin["card_id"], "checkin_yes", eir.id)
        for i in range(30, 100):
            sess3.tick(portal, 0, t0 + i)
        active_now = store3.get_task(eir.id).status
        for i in range(100, 240):
            sess3.tick(whatsapp, 0, t0 + i)
    finally:
        manager_mod.notifications_welcome = real_welcome
    kinds3 = [c.kind for c in ui3.shown]
    ok = checkin_shown and active_now == ACTIVE and "nudge" in kinds3
    failures += 0 if ok else 1
    print(f"  {'✓' if ok else '✗'} Check-in shown={checkin_shown} -> Yes -> {active_now}; after WhatsApp: cards={kinds3}")
    store3.close()

    print("      ...hotkeys: auto-repeat, tap vs hold, Esc, missed key-up")
    from .hotkey import HotkeyListener

    class FakeEngine:
        def __init__(self):
            self.is_listening, self.task_manager, self.calls = False, object(), []
        def start_dictation(self, route="dictate"):
            self.is_listening = True; self.calls.append(f"start:{route}")
        def stop_dictation(self):
            self.is_listening = False; self.calls.append("stop")
        def cancel_dictation(self):
            self.is_listening = False; self.calls.append("cancel")

    peek_events = []
    fe = FakeEngine()
    hk_cfg = Config(**{**config.__dict__, "mode": "toggle"})
    hk = HotkeyListener(fe, hk_cfg, actions={"ctrl+alt+q": peek_events.append})
    hk._bindings = hk._build()
    ok_mods = lambda mods: True
    t = 100.0
    hk.process("q", True, t, ok_mods)
    for i in range(30):                                  # held: Windows auto-repeat at ~33ms
        hk.process("q", True, t + 0.4 + i * 0.033, ok_mods)
    hk.process("q", False, t + 1.5, ok_mods)
    hk.process("t", True, t + 3.0, ok_mods); hk.process("t", False, t + 3.1, ok_mods)     # tap: start
    hk.process("t", True, t + 5.0, ok_mods); hk.process("t", False, t + 5.1, ok_mods)     # tap: stop
    hk.process("t", True, t + 7.0, ok_mods)                                              # hold 1s: push-to-talk
    for i in range(20):
        hk.process("t", True, t + 7.4 + i * 0.033, ok_mods)
    hk.process("t", False, t + 8.0, ok_mods)
    hk.process("d", True, t + 9.0, ok_mods); hk.process("d", False, t + 9.1, ok_mods)     # tap dictate
    hk.process("esc", True, t + 10.0, ok_mods)                                           # Esc cancels
    hk.process("t", True, t + 12.0, ok_mods)                                             # key-up never arrives...
    hk.process("t", True, t + 20.0, ok_mods)                                             # ...next press still works
    hk._jobs.join()
    want_calls = ["start:task", "stop", "start:task", "stop", "start:dictate", "cancel", "start:task", "stop"]
    peek_ok = peek_events[0] == "press" and len(peek_events) == 2 and peek_events[1][0] == "release"
    ok = fe.calls == want_calls and peek_ok
    failures += 0 if ok else 1
    print(f"  {'✓' if ok else '✗'} held Q -> {len(peek_events)} peek events (press+release); engine: {fe.calls}")

    print("      ...Undo button on a Done card")
    st4 = TaskStore(os.path.join(tmp, "undo.db"))
    ui4 = FakeUI()
    mgr4 = TaskManager(sim_cfg, st4, ui4, feedback, ai_client=None)
    tk = st4.add_task("Send invoice to Alpha")
    mgr4.set_status(tk.id, COMPLETED, card_id=1, via="test")
    mgr4.on_card_action(1, "undo", {"undo": (tk.id, "ready")})
    ok = st4.get_task(tk.id).status == "ready" and ui4.shown[-1].eyebrow == "Undone"
    failures += 0 if ok else 1
    print(f"  {'✓' if ok else '✗'} Done -> Undo -> {st4.get_task(tk.id).status}")
    st4.close()

    print("[7/7] Rendering every card type...")
    from .ui.cards import CardRenderer
    from .ui.theme import detect_theme
    from .ui.host import Card
    from .tasks import presenter
    theme = detect_theme()
    r = CardRenderer(theme, 1.0)
    p0 = time.perf_counter()
    task = store2.get_task(report.id)
    contents = (presenter.hello(config.hotkey, config.task_hotkey, config.peek_hotkey, 2),
                presenter.listening(config.task_hotkey, config.mode), presenter.thinking("x"),
                presenter.queued(task, 1, 3), presenter.done(task), presenter.removed(task),
                presenter.nudge(task, 600, "VS Code", config.task_hotkey), presenter.resume(task),
                presenter.checkin(task, "Edge", "Portal", 95), *[c for c, _ in presenter.pick("complete", [task], "dp world done")],
                *[c for c, _ in presenter.peek(store.open_tasks(), 1)])
    from .ui.paper import PaperRenderer
    paper = PaperRenderer(theme, 1.0)
    for rr in (r, paper):
        for content in contents:
            card = Card(1, content, time.time() - 0.3, level_fn=lambda: 0.02)
            card.h.snap(rr.height(content))
            img = rr.render(card, time.time() + 1.0)
            if rr is paper and not img.getchannel("A").getbbox():
                failures += 1
                print(f"  ✗ paper card '{content.kind}' rendered empty")
    print(f"  ✓ {len(contents)} card types x 2 styles (glass, paper) rendered in {(time.perf_counter() - p0) * 1000:.0f}ms "
          f"(theme: {theme.name}, reduced motion: {theme.reduce_motion}, high contrast: {theme.high_contrast})")
    key = get_secret("OPENROUTER_API_KEY")
    print(f"  {'✓' if key else '•'} OpenRouter key {'found' if key else 'not set: running rules-only'}")
    store.close()
    store2.close()
    return failures


def run_demo_ui(config: Config, feedback, project_dir: str):
    """Plays every card animation on screen, so the look (and your Lottie files) can be checked."""
    from .tasks import presenter
    from .tasks.models import Task
    from .ui.host import TaskCardHost

    ui = TaskCardHost(os.path.join(project_dir, config.animations_dir), style=config.card_style,
                      palette=config.paper_theme)
    ui.ready.wait(5)
    now = time.time()
    report = Task(1, "Finish November financial report", "Financial reporting", "high", "ready", now, now,
                  focus_seconds=1520, last_context="Nov Report - Google Sheets", last_app="Chrome",
                  last_active_at=now - 2600)
    bug = Task(2, "Fix OAuth redirect bug", "Billing", "normal", "paused", now, now, last_active_at=now - 900,
               last_context="engine.py · billing-service", last_app="VS Code")
    pr = Task(3, "Review Sarah's pricing PR", "Billing", "high", "ready", now, now)
    deck = Task(4, "Draft Q4 roadmap deck", "Planning", "normal", "waiting", now, now)
    live = Task(5, "Reply to the auditors", "Financial reporting", "normal", "active", now, now,
                last_context="Audit thread · mail.google.com", last_app="Chrome", last_active_at=now,
                last_url="https://mail.google.com/mail/u/0")
    level = {"v": 0.0}

    def step(seconds, fn=None):
        if fn:
            fn()
        time.sleep(seconds)

    hello = ui.show(presenter.hello(config.hotkey, config.task_hotkey, config.peek_hotkey, 5))
    time.sleep(2.2)
    ui.dismiss(hello)
    card = ui.show(presenter.listening(config.task_hotkey, config.mode), level_fn=lambda: level["v"])
    feedback.start_recording()
    for i in range(40):
        level["v"] = abs(math.sin(i / 3)) * 0.06
        time.sleep(0.05)
    step(1.2, lambda: ui.show(presenter.thinking("finish the november financial report"), card_id=card))
    step(1.4, lambda: (ui.show(presenter.queued(report, 2, 4), card_id=card), feedback.task_queued()))
    step(1.6, lambda: ui.show(presenter.queued(bug, 3, 4)))
    step(4.2, lambda: ui.show_group("peek", presenter.peek([live, bug, report, pr, deck], 2)))
    step(0.8, lambda: ui.dismiss_group("peek"))
    nudge = ui.show(presenter.nudge(report, 1520, "VS Code", config.task_hotkey), payload=1)
    step(2.6, feedback.nudge)
    step(2.0, lambda: (ui.show(presenter.done(report), card_id=nudge), feedback.task_done()))
    step(1.6, lambda: (ui.show(presenter.removed(bug)), feedback.task_removed()))
    step(6.5, lambda: ui.show(presenter.resume(bug)))
    ui.stop()
