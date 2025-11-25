from firestick_minder import _parse_pm_list_packages


def test_parse_pm_list_packages_strips_and_sorts():
    raw = """
    package:com.example.one
    package: com.example.two

    com.example.three
    """

    parsed = _parse_pm_list_packages(raw)

    assert parsed == [
        "com.example.one",
        "com.example.three",
        "com.example.two",
    ]
