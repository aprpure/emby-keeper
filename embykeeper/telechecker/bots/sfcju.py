from ._templ_a import TemplateACheckin


class SFCJUCheckin(TemplateACheckin):
    name = "非越助手"
    bot_username = "sfcju_Bot"
    bot_checkin_cmd = "/start"
    bot_use_captcha = False
