import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import transcription_state as state
from streamlit.testing.v1 import AppTest

def launch(interface):
    project = Path(__file__).resolve().parents[1]
    return AppTest.from_file(str(project / ("app.py" if interface == "app" else "transcribe.py")), default_timeout=120).run()

def button(at, label):
    return next(item for item in at.button if item.label == label)

def process(at, interface, path):
    if interface == "app":
        at.radio[0].set_value("Path (wildcards)").run()
        at.text_input[0].set_value(str(path)).run()
    else:
        at.checkbox[0].check().run()
        next(item for item in at.text_input if item.label == "File Path or Wildcard Pattern").set_value(str(path)).run()
    start(at, interface)


@pytest.fixture(autouse=True)
def clean_streamlit_context():
    # A bare import in the environment tests leaves a form on this context stack.
    from streamlit.delta_generator_singletons import context_dg_stack, get_default_dg_stack_value
    root, = get_default_dg_stack_value()
    previous_form = root._form_data
    root._form_data = None
    token = context_dg_stack.set((root,))
    yield
    context_dg_stack.reset(token)
    root._form_data = previous_form


@pytest.fixture
def allocations(tmp_path, monkeypatch):
    root = tmp_path / 'temporary'
    root.mkdir()
    real = tempfile.mkdtemp
    made = []
    def record(*args, **kwargs):
        result = real(*args, **kwargs)
        made.append(Path(result))
        return result
    monkeypatch.setattr(tempfile, 'tempdir', str(root))
    monkeypatch.setenv('TMPDIR', str(root))
    monkeypatch.setattr(tempfile, 'mkdtemp', record)
    yield made
    for path in made:
        shutil.rmtree(path, ignore_errors=True)


def assert_clean(allocations):
    assert all(not path.exists() for path in allocations)


def upload(at, names=('synthetic.wav',), *, interface):
    for name in names:
        at.file_uploader[0].upload(name, b'RIFF')
    if interface == 'divider':
        at.run()


def start(at, interface):
    button(at, 'Start Transcription' if interface == 'app' else '🎯 Start Transcription').click().run()


@pytest.mark.parametrize('interface', ['app', 'divider'])
def test_path_mode_is_caller_relative(interface, stub_whisper, monkeypatch):
    import librosa
    monkeypatch.setattr(librosa, 'load', lambda *a, **k: ([0] * 7, 2))
    path = Path('audio/synthetic.wav')
    path.parent.mkdir()
    path.write_bytes(b'RIFF')
    at = launch(interface)
    process(at, interface, './audio/synthetic.wav')
    assert not at.exception
    assert any('synthetic transcript' in x.value for x in at.text_area)


def test_path_mode_keeps_upload_prefixed_file(stub_whisper):
    path = Path('upload_notes.wav')
    path.write_bytes(b'RIFF')
    at = launch('app')
    process(at, 'app', str(path))
    assert path.exists()


@pytest.mark.parametrize('interface', ['app', 'divider'])
def test_upload_writes_nothing_to_cwd(interface, stub_whisper, allocations, monkeypatch):
    import librosa
    monkeypatch.setattr(librosa, 'load', lambda *a, **k: ([0] * 7, 2))
    at = launch(interface)
    upload(at, interface=interface)
    start(at, interface)
    assert not at.exception
    assert list(Path.cwd().iterdir()) == []
    assert any('synthetic transcript' in x.value for x in at.text_area)
    assert allocations
    assert_clean(allocations)


def test_app_upload_cleanup_on_failure(stub_whisper, allocations, monkeypatch):
    import whisper
    monkeypatch.setattr(whisper, 'load_model', lambda name: (_ for _ in ()).throw(RuntimeError('synthetic failure')))
    at = launch('app')
    upload(at, interface='app')
    start(at, 'app')
    assert any('synthetic failure' in x.value for x in at.error)
    assert_clean(allocations)


def test_divider_upload_cleanup_on_failure(stub_whisper, allocations, monkeypatch):
    import whisper, librosa
    monkeypatch.setattr(librosa, 'load', lambda *a, **k: ([0], 1))
    monkeypatch.setattr(whisper, 'load_model', lambda name: SimpleNamespace(transcribe=lambda path: (_ for _ in ()).throw(RuntimeError('synthetic failure'))))
    at = launch('divider')
    upload(at, interface='divider')
    start(at, 'divider')
    assert any('[ERROR]' in x.value for x in at.text_area)
    assert_clean(allocations)


def test_divider_rerun_makes_no_batch(stub_whisper, allocations, monkeypatch):
    at = launch('divider')
    upload(at, interface='divider')
    at.run()
    assert not allocations


def test_app_uses_selected_model(stub_whisper, monkeypatch):
    import whisper
    calls = []
    monkeypatch.setattr(whisper, 'load_model', lambda name: (calls.append(name), SimpleNamespace(transcribe=lambda path: {'text': 'synthetic transcript'}))[1])
    path = Path('sample.wav'); path.write_bytes(b'RIFF')
    at = launch('app')
    at.radio[0].set_value('Path (wildcards)').run()
    at.text_input[0].set_value(str(path)).run()
    at.selectbox[0].set_value('tiny')
    start(at, 'app')
    assert calls == ['tiny']


def test_divider_duration_falls_back_to_whisper(stub_whisper, monkeypatch):
    import librosa
    monkeypatch.setattr(librosa, 'load', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('synthetic failure')))
    path = Path('sample.wav'); path.write_bytes(b'RIFF')
    at = launch('divider'); process(at, 'divider', str(path))
    assert state.read_counters().counters.cumulative_seconds == 3.5
    assert any('synthetic transcript' in x.value for x in at.text_area)
    assert all('[ERROR]' not in x.value for x in at.text_area)


def fallback(at_interface, monkeypatch, key):
    import whisper, openai
    calls = []
    monkeypatch.setattr(whisper, 'load_model', lambda name: (_ for _ in ()).throw(RuntimeError('synthetic failure')))
    monkeypatch.setattr(openai, 'OpenAI', lambda **kwargs: (calls.append(kwargs), SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=lambda **kw: (calls.append(kw), 'fallback transcript')[1]))))[1])
    if key: monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-key')
    path = Path('sample.wav'); path.write_bytes(b'RIFF')
    at = launch(at_interface); process(at, at_interface, str(path))
    return at, calls


def test_app_fallback_needs_key(stub_whisper, monkeypatch):
    at, calls = fallback('app', monkeypatch, False)
    assert not calls and any('synthetic failure' in x.value for x in at.error)


def test_app_fallback_uses_key(stub_whisper, monkeypatch):
    at, calls = fallback('app', monkeypatch, True)
    assert len(calls) == 2 and calls[1]['model'] == 'whisper-1'
    assert any('fallback transcript' in x.value for x in at.text_area)


def test_divider_never_calls_openai(stub_whisper, monkeypatch):
    at, calls = fallback('divider', monkeypatch, True)
    assert not calls and any('synthetic failure' in x.value for x in at.error)


@pytest.mark.parametrize('interface', ['app', 'divider'])
@pytest.mark.parametrize('failure', ['allocation', 'write'])
def test_upload_write_failure_is_recoverable(interface, failure, stub_whisper, allocations, monkeypatch):
    import librosa
    monkeypatch.setattr(librosa, 'load', lambda *a, **k: ([0] * 7, 2))
    at = launch(interface)
    upload(at, ('one.wav', 'two.wav'), interface=interface)
    if interface == 'app':
        at.session_state['transcripts'] = {'old': SimpleNamespace(filename='old.wav', duration_seconds=1, timestamp='now', text='previous transcript')}
    else:
        at.session_state['raw_texts'] = ['previous transcript']
        at.session_state['processed_texts'] = ['']
        at.session_state['file_names'] = ['old.wav']
    original_alloc = getattr(state, 'new_upload_batch', lambda: None)
    original_write = getattr(state, 'write_upload', lambda *a: None)
    if failure == 'allocation':
        monkeypatch.setattr(state, 'new_upload_batch', lambda: (_ for _ in ()).throw(OSError('synthetic upload failure')), raising=False)
    else:
        def fail_second(batch, index, name, data):
            if index == 1:
                original_write(batch, index, name, b'partial')
                raise OSError('synthetic upload failure')
            return original_write(batch, index, name, data)
        monkeypatch.setattr(state, 'write_upload', fail_second, raising=False)
    start(at, interface)
    assert not at.exception
    assert any('synthetic upload failure' in x.value for x in at.error)
    assert any('previous transcript' in x.value for x in at.text_area)
    assert not any('Transcription completed successfully' in x.value for x in at.success)
    assert_clean(allocations)
    monkeypatch.setattr(state, 'new_upload_batch', original_alloc, raising=False)
    monkeypatch.setattr(state, 'write_upload', original_write, raising=False)
    if interface == 'app':
        upload(at, ('one.wav', 'two.wav'), interface=interface)
    start(at, interface)
    assert not at.exception
    assert any('synthetic transcript' in x.value for x in at.text_area)
    assert_clean(allocations)
