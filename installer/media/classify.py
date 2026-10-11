"""
Per-file verdicts for `vulcan media scan`:
- language rule: English audio, else original-language audio + English subtitles
  (embedded or sidecar). Extra dub tracks don't matter.
- direct play: will most devices play it without the server converting it?
"""

DIRECT_VIDEO = {"h264"}
DIRECT_AUDIO = {"aac", "ac3", "eac3", "mp3"}
TEXT_SUBS = {"subrip", "ass", "ssa", "mov_text", "webvtt", "text"}


def rule_status(info, sidecars, original_language):
    audio = {a["lang"] for a in info["audio"]}
    if "eng" in audio:
        return "ok", "English audio"
    if not original_language:
        return "ok", "original language unknown - not checked"
    subs = {s["lang"] for s in info["subs"]} | {s["lang"] for s in sidecars}
    if original_language not in audio:
        return "breaks", f"no English or original ({original_language}) audio"
    if "eng" not in subs:
        return "breaks", "original audio but no English subtitles"
    return "ok", "original audio + English subtitles"


def direct_play(info):
    reasons = []
    if info["vcodec"] not in DIRECT_VIDEO:
        reasons.append(f"video {info['vcodec']}")
    elif info["bit_depth"] != 8:
        reasons.append(f"{info['bit_depth']}-bit video")
    bad_audio = sorted({a["codec"] or "unknown" for a in info["audio"]} - DIRECT_AUDIO)
    if bad_audio:
        reasons.append("audio " + "/".join(bad_audio))
    bad_subs = sorted({s["codec"] or "unknown" for s in info["subs"]} - TEXT_SUBS)
    if bad_subs:
        reasons.append("picture subtitles " + "/".join(bad_subs))
    return not reasons, reasons
