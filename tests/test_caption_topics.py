# -*- coding: utf-8 -*-
"""Shared ``#topic`` parser for final public captions.

The parser is pure text: it never browses, clicks, or knows a platform's
candidate list. Tests here lock the token rules the publish commands rely on.
"""

from __future__ import annotations

from utils.caption_topics import (
    STATUS_TEXT,
    TopicResult,
    describe_caption_difference,
    parse_caption_topics,
    text_results,
)


def _spans(caption: str):
    return [
        (item.name, item.text, item.start, item.end, item.index)
        for item in parse_caption_topics(caption).occurrences
    ]


def test_caption_without_topics_keeps_the_original_text():
    caption = "今天喝了咖啡，配上栗子蛋糕。"

    report = parse_caption_topics(caption)

    assert report.text == caption
    assert report.occurrences == ()


def test_topics_keep_caption_order_duplicates_and_a_one_based_index():
    caption = "#b 中间 #a 结尾 #b"

    assert _spans(caption) == [
        ("b", "#b", 0, 2, 1),
        ("a", "#a", 6, 8, 2),
        ("b", "#b", 12, 14, 3),
    ]


def test_cjk_punctuation_ends_the_topic_and_stays_outside_it():
    caption = "今天喝了 #咖啡，配上 #栗子蛋糕。"

    assert _spans(caption) == [
        ("咖啡", "#咖啡", 5, 8, 1),
        ("栗子蛋糕", "#栗子蛋糕", 12, 17, 2),
    ]
    assert caption[8] == "，"
    assert caption[17] == "。"


def test_ascii_punctuation_ends_the_topic_and_case_is_preserved():
    caption = "#coffee, then #Coffee! (#Tea) #coffee"

    assert _spans(caption) == [
        ("coffee", "#coffee", 0, 7, 1),
        ("Coffee", "#Coffee", 14, 21, 2),
        ("Tea", "#Tea", 24, 28, 3),
        ("coffee", "#coffee", 30, 37, 4),
    ]


def test_underscore_letters_and_digits_stay_inside_the_topic():
    caption = "#咖啡_2 #a1_b"

    assert _spans(caption) == [
        ("咖啡_2", "#咖啡_2", 0, 5, 1),
        ("a1_b", "#a1_b", 6, 11, 2),
    ]


def test_whitespace_newlines_and_adjacent_hashes_bound_topics():
    caption = "#one\n#two\t#three#four"

    assert _spans(caption) == [
        ("one", "#one", 0, 4, 1),
        ("two", "#two", 5, 9, 2),
        ("three", "#three", 10, 16, 3),
        ("four", "#four", 16, 21, 4),
    ]


def test_hash_without_a_topic_character_is_ignored():
    caption = "# #， #! #\n#\t"

    assert parse_caption_topics(caption).occurrences == ()


def test_url_fragments_are_skipped_and_the_url_stays_verbatim():
    caption = (
        "见 https://example.com/page/#frag 与 http://Example.COM/#中文 "
        "及 www.example.com/#part 再 #真话题"
    )

    report = parse_caption_topics(caption)

    assert [(item.name, item.start, item.end) for item in report.occurrences] == [
        ("真话题", 84, 88)
    ]
    assert report.text == caption
    assert "https://example.com/page/#frag" in report.text
    assert "http://Example.COM/#中文" in report.text
    assert "www.example.com/#part" in report.text


def test_a_topic_next_to_a_url_is_not_taken_from_the_url():
    caption = "链接 https://example.com/#frag 之后 #topic"

    assert _spans(caption) == [("topic", "#topic", 32, 38, 1)]


def test_a_topic_immediately_after_a_url_fragment_without_a_space():
    caption = "详情https://example.com/#frag，#咖啡"

    report = parse_caption_topics(caption)

    assert [item.text for item in report.occurrences] == ["#咖啡"]
    item = report.occurrences[0]
    assert caption[item.start:item.end] == "#咖啡"


def test_a_fragment_without_a_path_is_still_part_of_the_url():
    caption = "见 https://example.com#咖啡 然后 #真话题"

    assert [item.text for item in parse_caption_topics(caption).occurrences] == [
        "#真话题"
    ]


def test_every_offset_points_into_the_original_caption():
    caption = "第一行 #A\n第二行 https://x.test/#frag 与 #b，结束"

    for item in parse_caption_topics(caption).occurrences:
        assert caption[item.start:item.end] == item.text
        assert caption[item.start] == "#"
        assert item.name == item.text[1:]


def test_text_results_keep_one_status_per_occurrence_in_order():
    report = parse_caption_topics("正文 #a 与 #a")

    results = text_results(report, reason="简介全文逐字回读一致")

    assert [result.occurrence.index for result in results] == [1, 2]
    assert [result.occurrence.text for result in results] == ["#a", "#a"]
    assert all(isinstance(result, TopicResult) for result in results)
    assert {result.status for result in results} == {STATUS_TEXT}
    assert [result.reason for result in results] == [
        "简介全文逐字回读一致",
        "简介全文逐字回读一致",
    ]


def test_text_results_are_empty_when_the_caption_has_no_topics():
    assert text_results(parse_caption_topics("没有话题")) == ()


def test_topic_result_as_dict_is_the_shared_result_schema():
    report = parse_caption_topics("正文 #a 与 #咖啡")
    results = text_results(report, reason="配文全文逐字回读一致")

    assert results[0].as_dict() == {
        "index": 1,
        "text": "#a",
        "name": "a",
        "start": 3,
        "end": 5,
        "status": STATUS_TEXT,
        "reason": "配文全文逐字回读一致",
    }
    assert results[1].as_dict() == {
        "index": 2,
        "text": "#咖啡",
        "name": "咖啡",
        "start": 8,
        "end": 11,
        "status": STATUS_TEXT,
        "reason": "配文全文逐字回读一致",
    }


def test_caption_difference_names_the_first_differing_character():
    assert (
        describe_caption_difference("今天 #咖啡，结束", "今天 #咖啡 结束")
        == "第 7 个字符不同：期望「，」，实际「 」；"
        "期望全文「今天 #咖啡，结束」，实际全文「今天 #咖啡 结束」"
    )


def test_caption_difference_makes_newlines_and_endings_visible():
    assert "期望「\\n」，实际「（结尾）」" in describe_caption_difference(
        "第一行\n", "第一行"
    )
    assert "实际「空格(U+00A0)」" in describe_caption_difference(
        "话题", "话题\u00a0"
    )
    assert describe_caption_difference("逐字一致", "逐字一致") == "全文一致"
    assert describe_caption_difference("正文", None) == "实际正文未读到"
