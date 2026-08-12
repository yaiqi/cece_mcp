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


class CompanyRef(EntityRef):
    company_name: str = Field(description="企业完整登记名称")


class GroupRef(EntityRef):
    group_id: str = Field(description="集团 ID")
    group_name: str = Field(description="集团全称")
    member_company_query_id: str = Field(
        alias="成员企业查询标识",
        description="查询集团成员企业所需的内部标识",
    )


class IndustryRef(EntityRef):
    industry_code: str = Field(description="产业分类代码")
    industry_type: str = Field(description="产业分类体系")


class ParkRef(EntityRef):
    park_id: str = Field(description="园区 ID")
    zjs_park_id: str = Field(description="园区 ZJS 格式 ID")
    park_name: str = Field(description="园区全称")


class PersonRef(EntityRef):
    person_no: str = Field(description="人物唯一编号")


class RegionRef(EntityRef):
    region_code: str = Field(description="行政区划代码")
    region_name: str = Field(description="区域名称")
    province_name: str = Field(description="省级区域名称")
    city_name: str = Field(description="市级区域名称")
    district_name: str = Field(description="区县名称")
