from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def build_resume_keyboard(resume_list: list) -> InlineKeyboardMarkup:
    """
    resume_list — список кортежей (resume_id, resume_name)
    """
    kb = InlineKeyboardMarkup(row_width=1)
    for r_id, r_name in resume_list:
        kb.add(InlineKeyboardButton(r_name, callback_data=f"select_resume_{r_id}"))
    return kb