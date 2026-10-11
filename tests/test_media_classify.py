from installer.media.classify import direct_play, rule_status


def info(audio, subs=(), vcodec="h264", bit_depth=8):
    return {"vcodec": vcodec, "bit_depth": bit_depth,
            "audio": [{"lang": a, "codec": c} for a, c in audio],
            "subs": [{"lang": s, "codec": c} for s, c in subs]}


def test_english_audio_is_always_ok():
    assert rule_status(info([("eng", "aac")]), [], "jpn")[0] == "ok"


def test_original_audio_plus_sidecar_english_is_ok_even_with_extra_dub():
    i = info([("fre", "aac"), ("jpn", "aac")], [("fre", "subrip")])
    assert rule_status(i, [{"path": "x.en.srt", "lang": "eng"}], "jpn")[0] == "ok"


def test_original_audio_without_english_subs_breaks():
    status, note = rule_status(info([("jpn", "aac")], [("spa", "subrip")]), [], "jpn")
    assert status == "breaks" and "no English subtitles" in note


def test_foreign_dub_only_breaks():
    assert rule_status(info([("ita", "aac")], [("eng", "subrip")]), [], "jpn")[0] == "breaks"


def test_unknown_original_language_is_ok_with_note():
    status, note = rule_status(info([("kor", "aac")]), [], None)
    assert status == "ok" and "unknown" in note


def test_direct_play_universal():
    assert direct_play(info([("eng", "aac")], [("eng", "subrip")])) == (True, [])


def test_direct_play_reasons():
    ok, reasons = direct_play(info([("eng", "truehd"), ("jpn", None)], [("eng", "hdmv_pgs_subtitle")],
                                   vcodec="hevc", bit_depth=10))
    assert not ok
    assert reasons == ["video hevc", "audio truehd/unknown", "picture subtitles hdmv_pgs_subtitle"]


def test_direct_play_flags_10bit_h264():
    assert direct_play(info([("eng", "aac")], bit_depth=10)) == (False, ["10-bit video"])
