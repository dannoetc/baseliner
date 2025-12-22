from fastapi import APIRouter

from baseliner_server.api.v1.admin import router as admin_router
from baseliner_server.api.v1.device import router as device_router
from baseliner_server.api.v1.enroll import router as enroll_router

router = APIRouter(prefix="/api/v1")
router.include_router(enroll_router)
router.include_router(device_router)
router.include_router(admin_router)
