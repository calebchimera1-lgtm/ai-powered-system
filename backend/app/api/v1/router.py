"""Version 1 API router."""

from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    categories,
    finance,
    media,
    products,
    purchasing,
    roles,
    sales,
    stock,
    suppliers,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(audit.router)
api_router.include_router(categories.router)
api_router.include_router(products.router)
api_router.include_router(suppliers.router)
api_router.include_router(stock.router)
api_router.include_router(sales.router)
api_router.include_router(purchasing.router)
api_router.include_router(finance.router)
api_router.include_router(media.router)
