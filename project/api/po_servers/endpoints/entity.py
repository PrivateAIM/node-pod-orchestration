import pydantic

class AnalyseLogsResponse(pydantic.BaseModel):
    list: pydantic.Any
