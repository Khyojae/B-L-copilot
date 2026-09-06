"""합성 데이터 생성 파이프라인 (설계서 5절).

pools → generator → injector → {rule_sim, review} 순서로 의존한다.
rule_sim.py 와 review.py 는 서로를 import 하지 않는다(설계서 1절 핵심 불변식).
"""

from __future__ import annotations
