from typing import Self

from pydantic import BaseModel, PostgresDsn, ValidationInfo, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseModel):
    workers: int = 5


class DB(BaseModel):
    host: str = 'localhost'
    port: int = 5432
    username: str = 'username'
    password: str = 'password'
    name: str = 'name'
    url: str = ''

    @model_validator(mode='after')
    def assemble_dsn(self, validation_info: ValidationInfo) -> Self:
        self.url = str(
            PostgresDsn.build(
                scheme='postgresql+asyncpg',
                username=self.username,
                password=self.password,
                host=self.host,
                port=int(self.port),
                path=self.name,
            )
        )
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            '.env.template',
            '.env.local',
        ),
        case_sensitive=False,
        env_nested_delimiter='__',
        extra='allow',
    )

    app: AppConfig = AppConfig()
    db: DB = DB()


settings = Settings()
