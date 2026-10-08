from app.youtube import YouTubeLive


class FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeBroadcasts:
    def __init__(self, response):
        self.response = response

    def list(self, **_kwargs):
        return FakeRequest(self.response)


class FakeAPI:
    def __init__(self, response):
        self.response = response

    def liveBroadcasts(self):
        return FakeBroadcasts(self.response)


def test_broadcast_status_returns_youtube_lifecycle_and_privacy():
    youtube = YouTubeLive.__new__(YouTubeLive)
    youtube.api = FakeAPI(
        {
            "items": [
                {
                    "status": {
                        "lifeCycleStatus": "live",
                        "privacyStatus": "public",
                    }
                }
            ]
        }
    )

    assert youtube.broadcast_status("broadcast-id") == {
        "life_cycle_status": "live",
        "privacy_status": "public",
    }


def test_broadcast_status_returns_none_when_youtube_does_not_find_it():
    youtube = YouTubeLive.__new__(YouTubeLive)
    youtube.api = FakeAPI({"items": []})

    assert youtube.broadcast_status("missing-id") is None
