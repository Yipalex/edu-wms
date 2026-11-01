"""幂等种子数据：6 类目、6 库位、编码规则单行、各分类流水种子、admin 账号。

可独立执行：`python -m app.seed`（建表兜底 + seed，幂等）。

流水种子来自 DESIGN.md 第 2 节「当前各分类流水已用量」：
教材 1→0032（next=33）、书籍 2→0000（next=1）、辅材 3→0042（next=43）、
耗材 4→0055（next=56）、礼品 5→0010（next=11）、其他 9→0014（next=15）。
重复执行不重复插入。
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import BarcodeRule, BarcodeSequence, Category, Location, User
from app.security import hash_password

logger = logging.getLogger(__name__)

CATEGORIES: list[tuple[str, str, int, int]] = [
    # (digit, name, sort_order, next_seq 存量种子)
    ("1", "教材", 1, 33),
    ("2", "书籍", 2, 1),
    ("3", "辅材", 3, 43),
    ("4", "耗材", 4, 56),
    ("5", "礼品", 5, 11),
    ("9", "其他", 6, 15),
]

LOCATIONS: list[tuple[str, str, str, bool, int]] = [
    # (code, name, type, is_front_warehouse, sort_order)
    ("HQ", "总校办仓库", "warehouse", True, 1),
    ("JC", "金城校区", "campus", False, 2),
    ("ST", "社坛校区", "campus", False, 3),
    ("HD", "海东校区", "campus", False, 4),
    ("MZ", "麻章校区", "campus", False, 5),
    ("KFQ", "开发区校区", "campus", False, 6),
]


def run_seed(db: Session) -> None:
    """幂等执行全部种子。"""
    _seed_categories(db)
    _seed_locations(db)
    db.flush()   # session autoflush=False：先落盘，供 _seed_admin 查 HQ 库位
    _seed_barcode_rule(db)
    _seed_admin(db)
    db.commit()


def _seed_categories(db: Session) -> None:
    for digit, name, sort_order, next_seq in CATEGORIES:
        cat = db.scalar(select(Category).where(Category.digit == digit))
        if cat is None:
            cat = Category(digit=digit, name=name, sort_order=sort_order)
            db.add(cat)
            db.flush()  # 拿到 id
            logger.info("seed: 创建类目 %s(%s)", name, digit)
        seq = db.scalar(select(BarcodeSequence).where(BarcodeSequence.category_id == cat.id))
        if seq is None:
            db.add(BarcodeSequence(category_id=cat.id, next_seq=next_seq))
            logger.info("seed: 类目 %s 流水种子 next_seq=%s", name, next_seq)


def _seed_locations(db: Session) -> None:
    for code, name, type_, is_front, sort_order in LOCATIONS:
        if db.scalar(select(Location).where(Location.code == code)) is None:
            db.add(Location(
                code=code, name=name, type=type_,
                is_front_warehouse=is_front, sort_order=sort_order,
            ))
            logger.info("seed: 创建库位 %s(%s)", name, code)


def _seed_barcode_rule(db: Session) -> None:
    if db.get(BarcodeRule, 1) is None:
        db.add(BarcodeRule(
            id=1, prefix="2", region_code="10",
            seq_width=4, total_length=8, allow_external=True,
        ))
        logger.info("seed: 创建编码规则（prefix=2 region=10 width=4）")


def _seed_admin(db: Session) -> None:
    username = settings.ADMIN_INIT_USERNAME
    if db.scalar(select(User).where(User.username == username)) is None:
        password = settings.ADMIN_INIT_PASSWORD
        if password == "Zexi@2026":
            logger.warning(
                "seed: admin 正在使用默认初始密码，上线后请立即通过「修改密码」更换！"
                "（可用环境变量 ADMIN_INIT_PASSWORD 指定）"
            )
        hq = db.scalar(select(Location).where(Location.code == "HQ"))
        db.add(User(
            username=username,
            password_hash=hash_password(password),
            display_name="系统管理员",
            role="admin",
            home_location_id=hq.id if hq else None,
            is_active=True,
        ))
        logger.info("seed: 创建 admin 账号 %s", username)


def main() -> None:
    """独立执行入口：`python -m app.seed`（deploy.sh 初始化时调用）。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from app.db import Base, SessionLocal, engine
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)   # sqlite 兜底；PG 生产走 alembic upgrade head（create_all 幂等）
    db = SessionLocal()
    try:
        run_seed(db)
        logger.info("seed 完成")
    finally:
        db.close()


if __name__ == "__main__":
    main()
