"""实体消歧成功后，查询工具使用的标准实体引用。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EntityRef(BaseModel):
    """禁止多余字段，并兼容现有业务代码的字典取值方式。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def __getitem__(self, key: str) -> Any:
        return self.model_dump(by_alias=True)[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.model_dump(by_alias=True).get(key, default)


class PersonRef(EntityRef):
    person_no: str = Field(description="人物唯一编号")
