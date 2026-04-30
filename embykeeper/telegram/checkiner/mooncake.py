from . import AnswerBotCheckin
from ._templ_a import TemplateACheckin


class MooncakeCheckin(TemplateACheckin, AnswerBotCheckin):
    name = "月饼"
    bot_username = "Moonkkbot"
    bot_text_ignore = ["点击图片中显示的数字"]
    bot_answer_button_message_pat = "点击图片中显示的数字"
    bot_use_history = 10
