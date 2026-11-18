#!/usr/bin/env python3
"""
audio_mix.py — Automated Audio Mixing (Voiceover + Auto-Ducking BGM + Beat-Synced SFX) & Pause Cutter
Part of the kinearc skill toolkit.

Requires: ffmpeg & ffprobe on PATH.

Subcommands:
1. mix: Mixes video + optional voiceover + optional BGM (with automatic sidechain ducking under voice)
        + optional timestamped SFX cues JSON -> finished MP4 or WAV/AAC.
   Example:
     python audio_mix.py mix --video render.mp4 --bgm music.mp3 --voice vo.wav --sfx cues.json --out final.mp4

2. cut-pauses: Uses ffmpeg silencedetect to find dead pauses in a voiceover or talking-head clip,
               writes cuts.json, and optionally exports a tight pause-free clip.
   Example:
     python audio_mix.py cut-pauses --input talking.mp4 --out tight.mp4 --threshold -32 --min_silence 0.45
"""

import argparse
import json
import os
import re
import subprocess
import sys


def get_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return float(out) if out else 0.0


def has_audio_stream(path: str) -> bool:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        path,
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return len(out) > 0


def cmd_mix(args):
    if not args.video and not args.out:
        raise ValueError("--out is required")

    target_dur = get_duration(args.video) if args.video else None
    inputs = []
    filter_parts = []
    idx = 0

    vid_idx = None
    if args.video:
        vid_idx = idx
        inputs += ["-i", args.video]
        idx += 1

    voice_idx = None
    if args.voice:
        voice_idx = idx
        inputs += ["-i", args.voice]
        idx += 1

    bgm_idx = None
    if args.bgm:
        bgm_idx = idx
        # Loop BGM if shorter than video
        if target_dur:
            inputs += ["-stream_loop", "-1", "-i", args.bgm]
        else:
            inputs += ["-i", args.bgm]
        idx += 1

    sfx_list = []
    if args.sfx:
        sfx_dir = os.path.dirname(os.path.abspath(args.sfx))
        with open(args.sfx, "r", encoding="utf-8") as f:
            cues = json.load(f)
        for cue in cues:
            cue_file = cue["file"]
            if not os.path.exists(cue_file) and not os.path.isabs(cue_file):
                for base_dir in (sfx_dir, os.path.dirname(sfx_dir)):
                    candidate = os.path.join(base_dir, cue_file)
                    if os.path.exists(candidate):
                        cue_file = candidate
                        break
            if not os.path.exists(cue_file):
                print(f"[audio_mix] Warning: SFX file not found, skipping: {cue['file']}", file=sys.stderr)
                continue
            sfx_list.append((idx, float(cue.get("time", 0.0)), float(cue.get("volume", 0.85))))
            inputs += ["-i", cue_file]
            idx += 1

    mix_labels = []

    # Keep original video audio if requested and present
    if args.keep_video_audio and args.video and has_audio_stream(args.video):
        filter_parts.append(f"[{vid_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={args.video_vol}[va]")
        mix_labels.append("[va]")

    # Prepare voice track (and split for sidechain ducking if BGM is present)
    if voice_idx is not None:
        voice_pad = f",apad=whole_dur={target_dur:.3f},atrim=0:{target_dur:.3f}" if target_dur else ""
        if bgm_idx is not None:
            filter_parts.append(f"[{voice_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={args.voice_vol}{voice_pad},asplit=2[vo_mix][vo_sc]")
        else:
            filter_parts.append(f"[{voice_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={args.voice_vol}{voice_pad}[vo_mix]")
        mix_labels.append("[vo_mix]")

    # Prepare BGM track with fade out and optional sidechain ducking under voiceover
    if bgm_idx is not None:
        dur_trim = f",atrim=0:{target_dur:.3f}" if target_dur else ""
        fade_out = f",afade=t=out:st={max(0.0, target_dur - args.fade_out):.3f}:d={args.fade_out:.3f}" if (target_dur and args.fade_out > 0) else ""
        filter_parts.append(f"[{bgm_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo{dur_trim},volume={args.bgm_vol}{fade_out}[bgm_base]")
        if voice_idx is not None:
            # Automatic sidechain compression: lowers BGM smoothly whenever voiceover speaks
            filter_parts.append("[bgm_base][vo_sc]sidechaincompress=threshold=0.02:ratio=6:attack=40:release=350:makeup=1[bgm_duck]")
            mix_labels.append("[bgm_duck]")
        else:
            mix_labels.append("[bgm_base]")

    # Delay and scale every timestamped SFX cue
    for k, (s_idx, t_sec, vol) in enumerate(sfx_list):
        ms = max(0, int(round(t_sec * 1000)))
        lbl = f"sfx{k}"
        filter_parts.append(f"[{s_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={vol},adelay={ms}|{ms}[{lbl}]")
        mix_labels.append(f"[{lbl}]")

    if not mix_labels:
        raise RuntimeError("No audio tracks provided to mix (specify at least --voice, --bgm, or --sfx).")

    out_dur_fix = f",apad=whole_dur={target_dur:.3f},atrim=0:{target_dur:.3f}" if target_dur else ""
    if len(mix_labels) == 1:
        filter_parts.append(f"{mix_labels[0]}alimiter=limit=0.95{out_dur_fix}[aout]")
    else:
        joined = "".join(mix_labels)
        filter_parts.append(f"{joined}amix=inputs={len(mix_labels)}:duration=longest:normalize=0,alimiter=limit=0.95{out_dur_fix}[aout]")

    filter_complex = ";".join(filter_parts)

    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", filter_complex]
    if vid_idx is not None:
        cmd += ["-map", f"{vid_idx}:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", args.out]
    else:
        cmd += ["-map", "[aout]", "-c:a", "aac" if args.out.endswith(".aac") or args.out.endswith(".m4a") else "pcm_s16le", args.out]

    subprocess.run(cmd, check=True)
    print(f"[audio_mix] Mixed {len(mix_labels)} audio stream(s) -> {args.out}")


def cmd_cut_pauses(args):
    dur = get_duration(args.input)
    cmd = [
        "ffmpeg", "-i", args.input,
        "-af", f"silencedetect=noise={args.threshold}dB:d={args.min_silence}",
        "-f", "null", "-",
    ]
    res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    stderr = res.stderr

    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", stderr)]
    if len(ends) < len(starts):
        ends.append(dur)

    pad = args.pad
    silences = list(zip(starts, ends))
    keep_segments = []
    cursor = 0.0
    for s_start, s_end in silences:
        seg_end = min(dur, s_start + pad)
        if seg_end - cursor > 0.08:
            keep_segments.append({"start": round(cursor, 3), "end": round(seg_end, 3)})
        cursor = max(cursor, s_end - pad)
    if dur - cursor > 0.08:
        keep_segments.append({"start": round(cursor, 3), "end": round(dur, 3)})

    cuts_out = args.cuts_json or os.path.splitext(args.out or args.input)[0] + "_cuts.json"
    with open(cuts_out, "w", encoding="utf-8") as f:
        json.dump({"input": args.input, "original_duration": round(dur, 3), "keep_segments": keep_segments}, f, indent=2)
    print(f"[audio_mix] Found {len(silences)} pauses -> {len(keep_segments)} active segments saved to {cuts_out}")

    if args.out and keep_segments:
        has_vid = False
        probe_v = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=index", "-of", "csv=p=0", args.input],
            text=True,
        ).strip()
        has_vid = len(probe_v) > 0

        parts = []
        concat_inputs = []
        for i, seg in enumerate(keep_segments):
            s, e = seg["start"], seg["end"]
            if has_vid:
                parts.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
                parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]")
                concat_inputs.append(f"[v{i}][a{i}]")
            else:
                parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]")
                concat_inputs.append(f"[a{i}]")

        if has_vid:
            parts.append(f"{''.join(concat_inputs)}concat=n={len(keep_segments)}:v=1:a=1[outv][outa]")
            fc = ";".join(parts)
            subprocess.run([
                "ffmpeg", "-y", "-i", args.input, "-filter_complex", fc,
                "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-b:a", "256k", args.out
            ], check=True)
        else:
            parts.append(f"{''.join(concat_inputs)}concat=n={len(keep_segments)}:v=0:a=1[outa]")
            fc = ";".join(parts)
            subprocess.run([
                "ffmpeg", "-y", "-i", args.input, "-filter_complex", fc,
                "-map", "[outa]", args.out
            ], check=True)
        print(f"[audio_mix] Exported pause-free clip -> {args.out}")


def main():
    parser = argparse.ArgumentParser(description="kinearc automated audio mixing & pause-cutting toolkit.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_mix = sub.add_parser("mix", help="Mix video + voiceover + auto-ducking BGM + timestamped SFX cues.")
    p_mix.add_argument("--video", help="Input video file (video stream copied losslessly)")
    p_mix.add_argument("--voice", help="Voiceover audio file")
    p_mix.add_argument("--bgm", help="Background music audio file (auto-looped & auto-ducked under voice)")
    p_mix.add_argument("--sfx", help="JSON file of SFX cues: [{\"file\": \"...\", \"time\": 1.5, \"volume\": 0.8}]")
    p_mix.add_argument("--out", required=True, help="Output MP4 or audio path")
    p_mix.add_argument("--voice_vol", type=float, default=1.0)
    p_mix.add_argument("--bgm_vol", type=float, default=0.35)
    p_mix.add_argument("--video_vol", type=float, default=1.0)
    p_mix.add_argument("--fade_out", type=float, default=1.5, help="BGM fade-out seconds at end of video")
    p_mix.add_argument("--keep_video_audio", action="store_true", help="Include original audio from --video in mix")

    p_cut = sub.add_parser("cut-pauses", help="Detect and trim silent pauses from voiceover or talking-head video.")
    p_cut.add_argument("--input", required=True, help="Input audio or video file")
    p_cut.add_argument("--out", help="Optional output trimmed audio/video file")
    p_cut.add_argument("--cuts_json", help="Path to write detected keep_segments JSON")
    p_cut.add_argument("--threshold", type=float, default=-32.0, help="Silence threshold in dB (default -32)")
    p_cut.add_argument("--min_silence", type=float, default=0.45, help="Minimum silence duration in seconds")
    p_cut.add_argument("--pad", type=float, default=0.08, help="Keep padding seconds around speech edges")

    args = parser.parse_args()
    if args.command == "mix":
        cmd_mix(args)
    elif args.command == "cut-pauses":
        cmd_cut_pauses(args)


if __name__ == "__main__":
    main()
