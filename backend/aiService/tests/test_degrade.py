"""스캔 열화 재현 테스트 (18번).

여기서 고정하는 것은 **재현성과 단계성**이다. "어느 축이 몇 % 떨어뜨리는가"는
환경과 원본에 달렸으므로 테스트에 박으면 다른 기계에서 깨진다. 대신 같은
시드가 같은 이미지를 내는지, 단계가 실제로 세지는지를 검사한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="numpy 미설치")
pytest.importorskip("cv2", reason="opencv-python 미설치")

from ocr import degrade  # noqa: E402
from ocr.degrade import (  # noqa: E402
    AXES,
    LEVELS,
    LIGHT,
    MODERATE,
    NONE,
    SEVERE,
    DegradationError,
    DegradationProfile,
)


@pytest.fixture
def page() -> "np.ndarray":
    """흰 종이에 검은 글자 줄. 서식 한 장을 대신한다."""
    img = np.full((400, 600), 255, dtype=np.uint8)
    for row in range(60, 340, 40):
        img[row:row + 12, 60:540] = 20
    return img


def _diff(a, b) -> float:
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


class TestDeterminism:
    """재현되지 않으면 재측정이 비교가 안 된다 (v2 10.3 난수 시드 요구)."""

    def test_같은_시드는_같은_이미지다(self, page):
        profile = DegradationProfile.uniform(MODERATE, seed=7)

        assert np.array_equal(
            degrade.degrade(page, profile), degrade.degrade(page, profile)
        )

    def test_다른_시드는_다른_이미지다(self, page):
        a = degrade.degrade(page, DegradationProfile.uniform(MODERATE, seed=7))
        b = degrade.degrade(page, DegradationProfile.uniform(MODERATE, seed=8))

        assert not np.array_equal(a, b)

    def test_축마다_독립된_난수를_쓴다(self, page):
        # 한 축의 단계를 바꿔도 다른 축의 결과가 흔들리면 안 된다. 흔들리면
        # "노이즈만 고쳤는데 도장 수치가 바뀌었다"가 되어 비교가 성립하지 않는다.
        only_stamp = DegradationProfile.single(degrade.STAMP, MODERATE, seed=5)
        with_others = DegradationProfile(
            levels={degrade.STAMP: MODERATE, degrade.NOISE: SEVERE}, seed=5
        )

        stamp_alone = degrade.degrade(page, only_stamp)
        # 도장만 다시 걸어도 같은 자리·같은 모양이어야 한다.
        assert np.array_equal(stamp_alone, degrade.degrade(page, only_stamp))
        assert not np.array_equal(stamp_alone, degrade.degrade(page, with_others))

    def test_프로세스가_달라도_같은_이미지다(self):
        """파이썬 문자열 해시는 PYTHONHASHSEED 로 프로세스마다 달라진다.

        축 구분에 그걸 쓰면 오늘 만든 열화와 내일 만든 열화가 달라지고,
        재현성이 존재 이유인 모듈이 조용히 무너진다. 해시 시드를 바꿔
        띄운 별도 프로세스와 결과를 대조한다.
        """
        import os
        import subprocess
        import sys
        import textwrap

        script = textwrap.dedent("""
            import hashlib
            import numpy as np
            from ocr import degrade
            from ocr.degrade import DegradationProfile
            img = np.full((120, 160), 255, dtype=np.uint8)
            img[40:52, 20:140] = 10
            out = degrade.degrade(img, DegradationProfile.uniform(2, seed=11))
            print(hashlib.sha256(out.tobytes()).hexdigest())
        """)

        digests = set()
        for hash_seed in ("0", "12345"):
            env = {**os.environ, "PYTHONHASHSEED": hash_seed}
            env["PYTHONPATH"] = str(Path(degrade.__file__).parent.parent)
            done = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, env=env, check=True,
            )
            digests.add(done.stdout.strip())

        assert len(digests) == 1, "해시 시드가 바뀌자 열화 결과가 달라졌다"


class TestLevels:
    def test_단계_0은_원본_그대로다(self, page):
        for axis in AXES:
            out = degrade.degrade(page, DegradationProfile.single(axis, NONE))
            assert np.array_equal(out, page), axis

    def test_단계가_올라가면_더_많이_망가진다(self, page):
        for axis in AXES:
            diffs = [
                _diff(page, degrade.degrade(page, DegradationProfile.single(axis, lv, seed=3)))
                for lv in (LIGHT, MODERATE, SEVERE)
            ]
            assert diffs[0] < diffs[1] < diffs[2], f"{axis}: {diffs}"

    def test_원본은_손대지_않는다(self, page):
        before = page.copy()
        degrade.degrade(page, DegradationProfile.uniform(SEVERE, seed=1))

        assert np.array_equal(page, before)

    def test_크기가_유지된다(self, page):
        # 해상도 열화는 줄였다 되돌린다. 작은 이미지를 그대로 주면 추출기가
        # 확대해 버려 열화가 아니라 크기 차이만 재게 된다.
        out = degrade.degrade(page, DegradationProfile.single(degrade.RESOLUTION, SEVERE))

        assert out.shape == page.shape

    def test_모르는_단계는_거부한다(self, page):
        with pytest.raises(DegradationError):
            degrade.degrade(page, DegradationProfile(levels={degrade.NOISE: 9}))

    def test_모르는_축은_거부한다(self):
        with pytest.raises(DegradationError):
            DegradationProfile.single("물에_젖음", LIGHT)


class TestSweep:
    def test_원본은_한_번만_들어간다(self, page):
        # 축마다 넣으면 같은 이미지가 다섯 번 나와 표를 읽는 사람이
        # 원본이 여러 개인 줄 알게 된다.
        profiles = [p for p, _ in degrade.sweep(page)]
        originals = [p for p in profiles if not any(p.levels.values())]

        assert len(originals) == 1

    def test_축_수_x_단계_수_만큼_나온다(self, page):
        expected = 1 + len(AXES) * (len(LEVELS) - 1)

        assert len(degrade.sweep(page)) == expected

    def test_축을_골라_돌릴_수_있다(self, page):
        result = degrade.sweep(page, axes=(degrade.NOISE,))

        assert len(result) == 1 + (len(LEVELS) - 1)


class TestProfileLabel:
    def test_원본_라벨(self):
        assert DegradationProfile(levels={}).label == "원본"

    def test_걸린_축만_적는다(self):
        profile = DegradationProfile(levels={degrade.NOISE: MODERATE, degrade.SKEW: NONE})

        assert profile.label == "노이즈2"

    def test_합성은_축_순서를_따른다(self):
        # 명세(v2 10.3 ④)의 열거 순서를 유지한다. 순서가 흔들리면 같은
        # 프로파일이 다른 이름으로 보고된다.
        profile = DegradationProfile.uniform(LIGHT)

        assert profile.label == "해상도1+기울기1+노이즈1+도장1+접힘1"


class TestStamp:
    def test_도장은_글자_위에_놓인다(self):
        # 여백에 찍으면 아무것도 가리지 않아 열화가 아니다.
        img = np.full((300, 300), 255, dtype=np.uint8)
        img[200:260, 200:280] = 0          # 글자 뭉치를 오른쪽 아래에만 둔다

        out = degrade.degrade(img, DegradationProfile.single(degrade.STAMP, SEVERE, seed=2))
        changed = np.abs(out.astype(np.int16) - img.astype(np.int16)) > 5

        # 변화의 무게중심이 글자 쪽에 있어야 한다.
        ys, xs = np.nonzero(changed)
        assert ys.mean() > 150 and xs.mean() > 150
