from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse


def MockResp(status, text):
    return AiohttpClientMockResponse("POST", None, status=status, text=text)
