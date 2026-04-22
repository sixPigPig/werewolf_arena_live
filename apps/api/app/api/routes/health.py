from fastapi import APIRouter


router = APIRouter()


@router.get("")
def read_health() -> dict[str, str]:
    return {"status": "ok"}
