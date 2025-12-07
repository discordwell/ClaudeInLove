"""
Token generator - create tracking links for scammer conversations.

Usage:
    from src.beacons.token_generator import TokenGenerator

    gen = TokenGenerator(base_url="https://yourdomain.com")
    link = gen.create_tracking_link(conversation_id="scammer_123", bait="Photo album")
    print(link)  # https://yourdomain.com/t/1?r=https://google.com
"""

from datetime import datetime
from typing import Optional
from urllib.parse import urlencode
import secrets

from .database import BeaconDatabase
from .models import BeaconToken


class TokenGenerator:
    """Generate tracking links and manage beacon tokens."""

    def __init__(self, base_url: str, db_path: str = "data/beacons.db"):
        """
        Initialize the token generator.

        Args:
            base_url: Your server's public URL (e.g., https://yourdomain.com)
            db_path: Path to the beacon database
        """
        self.base_url = base_url.rstrip("/")
        self.db = BeaconDatabase(db_path)

    def create_tracking_link(
        self,
        conversation_id: str,
        bait: str = "Photo",
        redirect_url: str = "https://drive.google.com/file/d/error",
    ) -> tuple[str, int]:
        """
        Create a tracking link that logs hits and redirects.

        Args:
            conversation_id: ID of the scammer conversation
            bait: Description of what the link supposedly is
            redirect_url: Where to redirect after logging (make it believable)

        Returns:
            Tuple of (tracking_link, token_id)
        """
        token = BeaconToken(
            id=None,
            conversation_id=conversation_id,
            token_type="link",
            token_url="",  # Will be set after we get the ID
            bait_description=bait,
            created_at=datetime.utcnow(),
            deployed_at=None,
            canary_token_id=None,
            manage_url=None,
        )

        token_id = self.db.create_token(token)

        # Build the tracking URL
        tracking_url = f"{self.base_url}/t/{token_id}?r={redirect_url}"

        return tracking_url, token_id

    def create_tracking_pixel(
        self, conversation_id: str, bait: str = "Email pixel"
    ) -> tuple[str, int]:
        """
        Create a 1x1 tracking pixel URL.

        Use in HTML emails: <img src="{pixel_url}" width="1" height="1">

        Returns:
            Tuple of (pixel_url, token_id)
        """
        token = BeaconToken(
            id=None,
            conversation_id=conversation_id,
            token_type="pixel",
            token_url="",
            bait_description=bait,
            created_at=datetime.utcnow(),
            deployed_at=None,
            canary_token_id=None,
            manage_url=None,
        )

        token_id = self.db.create_token(token)
        pixel_url = f"{self.base_url}/p/{token_id}.png"

        return pixel_url, token_id

    def create_gift_card_checker(
        self, conversation_id: str, bait: str = "Gift card balance checker"
    ) -> tuple[str, int]:
        """
        Create a fake gift card checker URL.

        Perfect for: "I scratched too hard, can you check if it works?"

        Returns:
            Tuple of (checker_url, token_id)
        """
        token = BeaconToken(
            id=None,
            conversation_id=conversation_id,
            token_type="gift_card",
            token_url="",
            bait_description=bait,
            created_at=datetime.utcnow(),
            deployed_at=None,
            canary_token_id=None,
            manage_url=None,
        )

        token_id = self.db.create_token(token)
        checker_url = f"{self.base_url}/gift-card-checker?t={token_id}"

        return checker_url, token_id

    def create_beacon_callback_url(
        self, conversation_id: str, bait: str = "Executable beacon"
    ) -> tuple[str, int]:
        """
        Create a callback URL for executable/document beacons.

        The beacon can POST system info to this URL:
            POST /b/{token_id}
            {"hostname": "...", "username": "...", "os": "..."}

        Or GET with query params:
            GET /b/{token_id}?h=hostname&u=username&o=Windows10

        Returns:
            Tuple of (callback_url, token_id)
        """
        token = BeaconToken(
            id=None,
            conversation_id=conversation_id,
            token_type="beacon",
            token_url="",
            bait_description=bait,
            created_at=datetime.utcnow(),
            deployed_at=None,
            canary_token_id=None,
            manage_url=None,
        )

        token_id = self.db.create_token(token)
        callback_url = f"{self.base_url}/b/{token_id}"

        return callback_url, token_id

    def mark_deployed(self, token_id: int):
        """Mark a token as deployed (sent to scammer)."""
        # TODO: Implement update in database
        pass

    def get_suggested_message(self, token_type: str, link: str) -> str:
        """
        Get a suggested 'confused elder' message for deploying the token.

        Returns a message template the persona can use.
        """
        templates = {
            "link": [
                f"I finally figured out how to share photos! My grandson helped me put them on the cloud. Can you see them here? {link}\nLet me know if it works, I'm not good with computers.",
                f"Here's that picture you wanted! I had to use the google drive thing. {link}\nI hope you can see it, technology is so confusing these days.",
            ],
            "pixel": [
                "I made you a little card, hope you like it!"  # Pixel embedded in HTML email
            ],
            "gift_card": [
                f"I got the cards like you asked but I scratched one too hard and can't read it! The lady at CVS said I can check if the money is still there. Can you try? {link}\nI'm so worried I ruined it.",
                f"Here are the gift card codes but one got damaged. My neighbor said you can check the balance here to make sure it works: {link}\nI'm sorry I'm such a klutz!",
            ],
            "beacon": [
                f"I made you a little slideshow of my garden! You have to download it though, I couldn't figure out the online way. {link}\nDouble click on it and let me know if my roses look nice!",
            ],
        }

        import random
        return random.choice(templates.get(token_type, templates["link"]))


# ============================================================
# CLI for manual token creation
# ============================================================


def main():
    """CLI for creating tracking tokens."""
    import argparse

    parser = argparse.ArgumentParser(description="Create beacon tracking tokens")
    parser.add_argument(
        "--base-url",
        required=True,
        help="Your server's public URL (e.g., https://yourdomain.com)",
    )
    parser.add_argument(
        "--conversation", "-c", required=True, help="Conversation ID to link token to"
    )
    parser.add_argument(
        "--type",
        "-t",
        choices=["link", "pixel", "gift_card", "beacon"],
        default="link",
        help="Type of token to create",
    )
    parser.add_argument("--bait", "-b", default="Photo", help="Bait description")
    parser.add_argument(
        "--redirect",
        "-r",
        default="https://drive.google.com/file/d/error",
        help="Redirect URL for link tokens",
    )

    args = parser.parse_args()

    gen = TokenGenerator(base_url=args.base_url)

    if args.type == "link":
        url, tid = gen.create_tracking_link(args.conversation, args.bait, args.redirect)
    elif args.type == "pixel":
        url, tid = gen.create_tracking_pixel(args.conversation, args.bait)
    elif args.type == "gift_card":
        url, tid = gen.create_gift_card_checker(args.conversation, args.bait)
    elif args.type == "beacon":
        url, tid = gen.create_beacon_callback_url(args.conversation, args.bait)

    print(f"\n Token created!")
    print(f"   Token ID: {tid}")
    print(f"   URL: {url}")
    print(f"\n Suggested message:")
    print(f"   {gen.get_suggested_message(args.type, url)}")


if __name__ == "__main__":
    main()
