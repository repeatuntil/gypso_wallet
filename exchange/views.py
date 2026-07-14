import requests
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects
import json

from django.contrib.auth.views import LoginView
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpRequest, HttpResponseNotFound, JsonResponse
from exchange.models import Profile, Token
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from exchange.forms import *
from django.views.generic import View, ListView, CreateView
from django.contrib.auth import authenticate, logout, login
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.urls import reverse_lazy


class Home(View):
    template_name = "exchange/index.html"

    def get(self, request, *args, **kwargs):
        u = None
        if request.user.is_authenticated:
            u = request.user
        return render(request, self.template_name, {"user": u})


class Registration(CreateView):
    form_class = RegisterForm
    template_name = 'exchange/register.html'
    success_url = reverse_lazy("home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Регистрация"
        return context


class Login(LoginView):
    authentication_form = LoginForm
    template_name = 'exchange/login.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Авторизация"
        return context

    def get_success_url(self):
        return reverse_lazy("home")


def logout_view(request):
    logout(request)
    return redirect("home", permanent=True)


def page_not_found(request, exception):
    return HttpResponseNotFound("page not found")


@method_decorator(login_required, name='dispatch')
class ProfileView(View):
    form_class = ProfileForm
    template_name = 'exchange/profile.html'
    url_base = 'https://api.coingecko.com/api/v3/simple/price'

    def post(self, request):
        form = self.form_class(request.POST, request.FILES)
        if form.is_valid():
            print(form.cleaned_data)
            profile_image, desc = form.cleaned_data["photo"], form.cleaned_data["description"]
            u = request.user
            if profile_image:
                u.profile.photo = profile_image
            u.profile.description = desc
            u.save()
        else:
            form.add_error("description", "Форма некорректна")
        return render(request, self.template_name, {"form": form, "user": request.user})

    def get(self, request):
        user_tokens = Token.objects.filter(profile=request.user.profile.id)
        parameters = {
            'ids': ",".join(list(map(str, user_tokens))),
            'vs_currencies': "usd",
            'precision': 3
        }
        sess = requests.Session()
        total_price = 0
        try:
            response = sess.get(self.url_base, params=parameters)
            profile_tokens_data = json.loads(response.text)
            for token in user_tokens:
                profile_tokens_data[token.name]["count"] = token.count
                total_price += token.count * float(profile_tokens_data[token.name]["usd"])
            print(profile_tokens_data)
        except (ConnectionError, Timeout, TooManyRedirects) as e:
            profile_tokens_data = {}
        form = self.form_class(initial={"description": request.user.profile.description, })
        return render(request, self.template_name, {"form": form, "user": request.user, "prices": profile_tokens_data, "total_price": total_price})


coins = ["bitcoin", "ethereum", "ripple", "litecoin", "binancecoin", "dogecoin", "solana"]
vs_currencies = ["usd", "eur", "rub"]
colors = {
    "bitcoin": "#8e5ea2",
    "ethereum": "#3e95cd",
    "ripple": "#3cba9f",
    "litecoin": "#e8c3b9",
    "binancecoin": "#c45850",
    "dogecoin": "#c4bd97",
    "solana": "#1d45ab"
}


@method_decorator(login_required, name='dispatch')
class Market(View):
    template_name = 'exchange/market.html'
    global coins

    def get(self, request):
        return render(request, self.template_name, {"user": request.user, "crypto_data": coins, "vs_currencies": vs_currencies, "title": "Биржа"})

    def post(self, request):
        data = json.loads(json.dumps(request.POST))
        type_, count, price = data["type"], float(data["count"]), float(data["price"])
        try:
            token = Token.objects.get(profile=request.user.profile.id, name=data['coin'])
            if type_ == "buy":
                token.count += count
                request.user.profile.balance -= count * price
            elif type_ == "sell":
                token.count -= count
                request.user.profile.balance += count * price
            token.save()
            request.user.save()
        except ObjectDoesNotExist:
            if type_ == "buy":
                token = Token(name=data['coin'], count=data['count'], profile=request.user.profile)
                request.user.profile.balance -= count * price
                token.save()
                request.user.save()
        return render(request, self.template_name, {"user": request.user, "crypto_data": coins, "vs_currencies": vs_currencies, "title": "Биржа"})


@login_required
def balance_data(request):
    global coins
    json_response = {
        "balance": request.user.profile.balance,
        "coin_count": {}
    }
    for coin in coins:
        json_response["coin_count"][coin] = 0
    user_tokens = Token.objects.filter(profile=request.user.profile.id)
    for token in user_tokens:
        json_response["coin_count"][token.name] = token.count
    return JsonResponse(json_response)


@login_required
def price_data(request):
    global coins, vs_currencies
    url_base = 'https://api.coingecko.com/api/v3/simple/price'
    parameters = {
        'ids': ",".join(coins),
        'vs_currencies': ",".join(vs_currencies),
        'precision': 3
    }
    sess = requests.Session()
    try:
        response = sess.get(url_base, params=parameters)
        if response.status_code == 429:
            return JsonResponse(request.session.get("last_available_price"))
        price_info = json.loads(response.text)
        json_response = {
            "prices": price_info,
            "coins": coins
        }
        request.session["last_available_price"] = json_response
        return JsonResponse(json_response)
    except (ConnectionError, Timeout, TooManyRedirects) as e:
        return HttpResponse(e)


@method_decorator(login_required, name='dispatch')
class Crypto(View):
    template_name = 'exchange/crypto.html'
    global coins

    def get(self, request):
        return render(request, self.template_name, {"user": request.user, "crypto_data": coins, "title": "Рынок"})


@login_required
def charts_data(request, coin, days):
    global coins
    url_base = 'https://api.coingecko.com/api/v3/coins/'
    parameters = {
        'vs_currency': "usd",
        'days': days,
        'interval': "daily",
    }
    sess = requests.Session()
    try:
        response = sess.get(url_base + f"{coin}/market_chart", params=parameters)
        if response.status_code == 429:
            return JsonResponse(request.session.get(f"{coin}_last_json"))
        coin_info = json.loads(response.text)
        print(coin_info)
        json_response = {
            "title": f"coins price info for {days} days",
            "data": {
                "labels": list(range(days + 1)),
                "datasets": [{
                    "label": coin,
                    "borderColor": colors[coin],
                    "data": [pair[1] for pair in coin_info["prices"]]
                }]
            }
        }
        request.session[f"{coin}_last_json"] = json_response
        return JsonResponse(json_response)
    except (ConnectionError, Timeout, TooManyRedirects) as e:
        return HttpResponse(e)


@login_required
def charts_options(request):
    global coins
    return JsonResponse({
        "options": list(range(7, 43)),
        "coins": coins
    })
