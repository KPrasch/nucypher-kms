from collections import defaultdict
from functools import wraps
from logging import Logger
from typing import Callable, List, Union, T, Any

import maya
import requests
from twisted.internet import reactor, threads
from twisted.internet.defer import Deferred
from twisted.mail.smtp import sendmail


class BaseEvent:

    title = NotImplemented

    def __init__(self):
        self.timestamp = maya.now()


class Message(BaseEvent):

    title = 'Event Message'

    def __init__(self, body: str):
        self.body = body
        super().__init__()


class ConfirmActivity(BaseEvent):

    title = 'Node Confirmed Activity'

    def __init__(self, success: bool, receipt: dict):
        self.success = success
        self.receipt = receipt
        super().__init__()


class Crash(BaseEvent):
    def __init__(self, reason, traceback: bool = None):
        self.reason = reason
        self.traceback = traceback
        super().__init__()


class EventBus:

    class UnknownEvent(ValueError):
        pass

    def __init__(self):
        self.__events = defaultdict(list)
        self.log = Logger(self.__class__.__name__)

    def __getitem__(self, event: Union[T, BaseEvent, str]) -> List[Callable]:
        """Get event subscribers by class, instance, or name."""
        if isinstance(event, BaseEvent):
            event_name = event.__class__.__name__
        elif issubclass(event, BaseEvent):
            event_name = event.__name__
        elif isinstance(event, str):
            event_name = event
        else:
            raise self.UnknownEvent(f"Got '{event}'")
        return self.__events[event_name]

    def on(self, events: List[BaseEvent], active: bool = True) -> Callable:
        """Decorator for event subscription"""
        def outer(func):
            if active:
                self.subscribe(events=events, function=func)

            @wraps(func)
            def wrapped(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapped
        return outer

    def _is_event(self, event: Any) -> bool:
        return isinstance(event, BaseEvent) or issubclass(event, BaseEvent)

    @property
    def events(self) -> int:
        """Returns total number of events with subscribers"""
        return len([e for e in self.__events if len(e) > 0])

    @property
    def subscriptions(self) -> int:
        """Return number of total subscribers"""
        return sum(len(callables) for callables in self.get_subscriptions())

    def subscribe(self, events: List[BaseEvent], function: Callable) -> None:
        try:
            for event in events:
                self[event].append(function)
        except TypeError:
            if self._is_event(events):
                self[events].append(function)
            else:
                raise self.UnknownEvent(str(events))

    def unsubscribe(self, function: Callable, event: BaseEvent) -> None:
        self[event].remove(function)

    def get_subscriptions(self, event: BaseEvent = None) -> list:
        if event:
            return self[event]
        return list(self.__events.values())

    def _success(self, *args, **kwargs):
        print(args, kwargs)

    def _error(self, failure, crash: bool = True):
        if crash:
            failure.raiseException()

    def emit(self, event: BaseEvent, threaded: bool = True, *args, **kwargs) -> None:
        subscriptions = self.get_subscriptions(event=event)

        # In-Parallel
        if threaded:
            for function in subscriptions:
                d = threads.deferToThread(function, event, *args, **kwargs)
                d.addCallbacks(self._success, self._error)

        # In-Series
        else:
            for func in subscriptions:
                func(event, *args, **kwargs)


events = EventBus()


@events.on([ConfirmActivity, Message])
def echo(event, *args, **kwargs) -> None:
    print(event.title, args, kwargs)


@events.on([ConfirmActivity], active=False)
def webhook(event, url, params, auth: bool) -> dict:
    response = requests.post(url=url, params=params)
    return response.json()


@events.on([ConfirmActivity], active=False)
def email(event: BaseEvent, ursula: dict, work: dict) -> Deferred:

    d = sendmail(smtphost=b"smtp.gmail.com",
                 from_addr=b"kieranprasch@gmail.com",
                 to_addrs=["kieranprasch@gmail.com"],
                 msg="This is my super awesome email, sent with Twisted!",
                 port=587, username="kieranprasch@gmail.com", password="*********")

    d.addBoth(print)
    return d


# Test Usage
events.emit(ConfirmActivity(success=True, receipt={}))
events.emit(Message(body="Lllamas"))

reactor.run()
