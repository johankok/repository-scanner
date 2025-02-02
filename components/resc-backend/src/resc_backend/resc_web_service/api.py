# pylint: disable=C0413,W0611,W0404
# Standard Library
import logging.config

# Third Party
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse
from starlette.status import HTTP_302_FOUND
from tenacity import RetryError

# First Party
from resc_backend.common import get_package_version
from resc_backend.constants import RWS_VERSION_PREFIX
from resc_backend.db.connection import Session, engine
from resc_backend.helpers.environment_wrapper import validate_environment
from resc_backend.resc_web_service.configuration import (
    AUTHENTICATION_REQUIRED,
    CORS_ALLOWED_DOMAINS,
    ENABLE_CORS,
    WEB_SERVICE_ENV_VARS
)
from resc_backend.resc_web_service.dependencies import (
    check_db_initialized,
    requires_auth,
    requires_no_auth,
    add_security_headers
)
from resc_backend.resc_web_service.endpoints import (
    common,
    detailed_findings,
    findings,
    health,
    metrics,
    repositories,
    rules,
    rule_packs,
    scans,
    vcs_instances
)
from resc_backend.resc_web_service.helpers.exception_handler import add_exception_handlers
from resc_backend.resc_web_service.cache_manager import CacheManager

# Check and load environment variables
env_variables = validate_environment(WEB_SERVICE_ENV_VARS)


def generate_logger_config(log_file_path, debug=True):
    """A function to generate the global logger config dictionary

    Arguments:
        log_file_path {string} -- Path where the logs are to be stored

    Keyword Arguments:
        debug {bool} -- Whether the logging level should be set to DEBUG or INFO (default: {True})

    Returns:
        Dict -- A dictionary containing the logger configuration
    """

    logging_level = "DEBUG" if debug else "INFO"
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "generic-log-formatter": {
                "format": "[%(levelname)s] [%(name)s] [%(asctime)s] %(message)s"
            },
        },
        "handlers": {
            "console": {
                "level": logging_level,
                "class": "logging.StreamHandler",
                "formatter": "generic-log-formatter",
            },
            "file": {
                "level": logging_level,
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "generic-log-formatter",
                "filename": log_file_path,
                "maxBytes": 100 * 1024 * 1024,
                "backupCount": 5
            }
        },
        "loggers": {
            "": {
                "handlers": ["console", "file"],
                "level": logging_level,
                "propagate": True
            },
        }
    }

    return logging_config


logging.config.dictConfig(generate_logger_config('local_logs.log'))
logger = logging.getLogger(__name__)
tags_metadata = [
    {"name": "health", "description": "Checks health for API"},
    {"name": "resc-common", "description": "Manage common information"},
    {"name": "resc-rules", "description": "Manage rule information"},
    {"name": "resc-rule-packs", "description": "Manage rule pack information"},
    {"name": "resc-repositories", "description": "Manage repository information"},
    {"name": "resc-scans", "description": "Manage scan information"},
    {"name": "resc-findings", "description": "Manage findings information"},
    {"name": "resc-vcs-instances", "description": "Manage vcs instance information"},
    {"name": "resc-metrics", "description": "Retrieve metrics"},
]

# Check if authentication is required for api endpoints
auth_disabled = env_variables[AUTHENTICATION_REQUIRED].lower() in ["false"]
AUTH = [Depends(requires_no_auth)] if auth_disabled else [Depends(requires_auth)]

app = FastAPI(title="Repository Scanner (RESC)",
              description="RESC API helps you to perform several operations upon findings "
                          "obtained from multiple source code repositories.",
              version=get_package_version(),
              openapi_tags=tags_metadata)

if env_variables[ENABLE_CORS].lower() in ["true"]:
    origins = env_variables[CORS_ALLOWED_DOMAINS].split(', ')
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health.router, prefix=RWS_VERSION_PREFIX)
app.include_router(common.router, prefix=RWS_VERSION_PREFIX, dependencies=AUTH)
app.include_router(rules.router, prefix=RWS_VERSION_PREFIX, dependencies=AUTH)
app.include_router(rule_packs.router, prefix=RWS_VERSION_PREFIX, dependencies=AUTH)
app.include_router(findings.router, prefix=RWS_VERSION_PREFIX, dependencies=AUTH)
app.include_router(detailed_findings.router, prefix=RWS_VERSION_PREFIX, dependencies=AUTH)
app.include_router(repositories.router, prefix=RWS_VERSION_PREFIX, dependencies=AUTH)
app.include_router(scans.router, prefix=RWS_VERSION_PREFIX, dependencies=AUTH)
app.include_router(vcs_instances.router, prefix=RWS_VERSION_PREFIX, dependencies=AUTH)
app.include_router(metrics.router, prefix=RWS_VERSION_PREFIX, dependencies=AUTH)

# Apply the security headers to the app in the form of middleware
app.middleware("http")(add_security_headers)

# Add exception handlers
add_exception_handlers(app=app)


@app.on_event("startup")
def app_startup():
    CacheManager.initialize_cache(env_variables=env_variables)
    try:
        _ = Session(bind=engine)
        check_db_initialized()

        logger.info("Database is connected, expected table(s) found")
    except RetryError as exc:
        raise SystemExit("Error while connecting to the database, retry timed out") from exc


@app.on_event("shutdown")
async def app_shutdown():
    await CacheManager.clear_all_cache()


@app.get("/")
def view_docs():
    return RedirectResponse(url="/docs", status_code=HTTP_302_FOUND)
