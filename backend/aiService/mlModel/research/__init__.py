"""F3 계층 B — 하자 확률 예측(XGBoost) 파이프라인.

기획안 5.3, 10.1, 10.3, 10.4 구현. 설계서: docs/F3_예측모델_설계.md.
이 패키지는 기존 src/smart_e_bl/ 과 독립적으로 자기완결적으로 동작한다
(설계서 3절). registry.py 만 예외적으로 ORM 을 지연 import 한다.
"""

from __future__ import annotations
