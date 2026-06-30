"""Behavioural tests for the Ghostscript PDF compression flags.

These assert the *command* we hand to Ghostscript, so they run without a real
`gs` binary (subprocess.run is stubbed). They lock in the DPI hard-cap and the
CMYK->RGB colour conversion that keep compression results consistent.
"""

import compression


def _capture_gs_cmd(monkeypatch, quality):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        out_path = next(a.split("=", 1)[1] for a in cmd if a.startswith("-sOutputFile="))
        with open(out_path, "wb") as fh:
            fh.write(b"%PDF-1.4\n%%EOF\n")

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(compression.subprocess, "run", fake_run)
    compression._compress_pdf_ghostscript(b"%PDF-1.4\n%%EOF\n", quality)
    return captured["cmd"]


def test_dpi_hardcap_matches_preset(monkeypatch):
    expected = {"screen": 72, "ebook": 150, "printer": 300}
    for quality, dpi in expected.items():
        cmd = _capture_gs_cmd(monkeypatch, quality)
        assert f"-dColorImageResolution={dpi}" in cmd
        assert f"-dGrayImageResolution={dpi}" in cmd
        # Threshold 1.0 makes downsampling fire for any image above target.
        assert "-dColorImageDownsampleThreshold=1.0" in cmd


def test_cmyk_to_rgb_only_for_web_presets(monkeypatch):
    for quality in ("screen", "ebook"):
        cmd = _capture_gs_cmd(monkeypatch, quality)
        assert "-sColorConversionStrategy=RGB" in cmd
        assert "-dConvertCMYKImagesToRGB=true" in cmd

    # `printer` preserves the original colour space for print fidelity.
    cmd = _capture_gs_cmd(monkeypatch, "printer")
    assert "-sColorConversionStrategy=RGB" not in cmd
    assert "-dConvertCMYKImagesToRGB=true" not in cmd


def test_unknown_quality_falls_back_to_default_dpi(monkeypatch):
    cmd = _capture_gs_cmd(monkeypatch, "bogus")
    # Default quality is "ebook" -> 150 dpi.
    assert "-dColorImageResolution=150" in cmd
