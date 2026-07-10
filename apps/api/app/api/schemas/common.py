from pydantic import BaseModel


class PaginationResponse(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int
