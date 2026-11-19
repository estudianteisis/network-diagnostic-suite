from netdiag.system_context import collect_start_context, finish_context


def test_context_contains_identity_process_and_traffic():
    context = collect_start_context()
    assert context["identity"]["user"]
    assert context["processes_at_start"]["running_count"] > 0
    finished = finish_context(context, 2.0)
    assert finished["session_traffic"]["average_download_mbps"] >= 0
    assert finished["processes_at_start"]["bandwidth_attribution_available"] is False
