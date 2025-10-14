import telebot
import os
from telebot import types
@bot.message_handler(commands=['start'])
def start(message):

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton('Куда обратиться за получением бесплатной юридической помощи')
    btn2 = types.KeyboardButton('Какие документы необходимы для приема')
    btn3 = types.KeyboardButton('Часто задаваемые вопросы')
    btn4 = types.KeyboardButton('Кто проводит консультации')
    markup.row(btn1, btn2)
    markup.row(btn3, btn4)
    bot.send_message(message.from_user.id, 'Чем я могу быть вам полезен?', reply_markup=markup)

@bot.message_handler(content_types=['text'])
def get_text_messages(message):

    if message.text == 'Часто задаваемые вопросы':
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn1 = types.KeyboardButton('Какую консультацию можно получить')
        btn2 = types.KeyboardButton('В какие сроки будет подготовлен ответ или необходимый правовой документ')
        btn3 = types.KeyboardButton('Представляют ли клиницисты интересы посетителей в суде')
        btn4 = types.KeyboardButton('Назад')
        markup.row(btn1)
        markup.row(btn2)
        markup.row(btn3)
        markup.row(btn4)
        bot.send_message(message.from_user.id, 'Выберите интересующий вас вопрос.', reply_markup=markup)

    elif message.text == 'Назад':
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn1 = types.KeyboardButton('Куда обратиться за получением бесплатной юридической помощи')
        btn2 = types.KeyboardButton('Какие документы необходимы для приема')
        btn3 = types.KeyboardButton('Часто задаваемые вопросы')
        btn4 = types.KeyboardButton('Кто проводит консультации')
        markup.row(btn1, btn2)
        markup.row(btn3, btn4)
        bot.send_message(message.from_user.id, "Чем я могу быть вам полезен?", reply_markup=markup)

    elif message.text == 'Куда обратиться за получением бесплатной юридической помощи':
        bot.send_message(message.from_user.id, '- Адрес: 40 лет Победы, 11, каб 1.16 \n- Режим работы: вторник с 14.00 до 18.00, суббота с 9.00 до 13.00 \n- контактный телефон: 51-55-17, 51-53-00 \n- адрес электронной почты: stud.cons@vgi.volsu.ru \n- страница в сети Интернет: \nhttps://vgi2.volsu.ru/structure/department/kafedra-yurisprudentsii/uclinic/', parse_mode='Markdown')

    elif message.text == 'Какие документы необходимы для приема':
        bot.send_message(message.from_user.id, '- документ, удостоверяющий личность \n- документы по проблеме юридического характера', parse_mode='Markdown')

    elif message.text == 'Кто проводит консультации':
        bot.send_message(message.from_user.id, 'Консультации проводят обучающиеся по направлению подготовки магистратура, помощники бакалавры под контролем преподавателей', parse_mode='Markdown')
        
    elif message.text == 'Какую консультацию можно получить':
        bot.send_message(message.from_user.id, '- устное разъяснение \n- письменный ответ \n- документ правового характера, с которым граждане обращаются в органы исполнительной власти и суды', parse_mode='Markdown')
        
    elif message.text == 'В какие сроки будет подготовлен ответ или необходимый правовой документ':
        bot.send_message(message.from_user.id, 'В  зависимости от сложности вопроса и при наличии полного пакета необходимых документов в среднем 7 дней, срок может быть увеличен', parse_mode='Markdown')

    elif message.text == 'Представляют ли клиницисты интересы посетителей в суде':
        bot.send_message(message.from_user.id, '- Согласно Положению о юридической клинике, нет \n- При необходимости и наличии доверительных отношений заявителя со студентами, имеющими высшее юридическое образование представительство возможно в личном порядке', parse_mode='Markdown')

bot.infinity_polling()
