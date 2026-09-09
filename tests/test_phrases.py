from core.phrases import split_input_phrases


def test_split_input_phrases_on_newlines():
    assert split_input_phrases("first query\nsecond query") == [
        "first query",
        "second query",
    ]


def test_split_input_phrases_on_commas():
    assert split_input_phrases("first query, second query") == [
        "first query",
        "second query",
    ]


def test_split_input_phrases_deduplicates():
    assert split_input_phrases("Same query\nsame query, Same query") == ["Same query"]


def test_split_input_phrases_ignores_blank_lines():
    assert split_input_phrases("one\n\n  \n,two") == ["one", "two"]
