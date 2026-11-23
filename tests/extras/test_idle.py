from watson.extras import idle


def test_non_windows_is_unsupported():
    assert idle.get_idle_provider("linux") is idle.unsupported_idle
    assert idle.unsupported_idle() is None
    assert not idle.is_supported("darwin")


def test_windows_provider_selected():
    assert idle.get_idle_provider("win32") is idle.windows_idle
    assert idle.is_supported("win32")
