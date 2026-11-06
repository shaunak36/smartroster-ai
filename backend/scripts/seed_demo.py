from __future__ import annotations

import json

from app.db.session import SessionLocal
from app.services.demo_data import seed_demo_data


def main() -> None:
    with SessionLocal() as session:
        summary = seed_demo_data(session)
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
