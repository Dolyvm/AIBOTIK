from typing import Optional, Literal

from pydantic import BaseModel

nationality_to_prompt = {
    "american": {
        "anime": "",
        "real": "american caucasian woman, white european descent, fair pink-toned skin, western facial features, round large eyes, straight or wavy hair, defined nose bridge, caucasian bone structure, NOT asian NOT oriental NOT japanese"
    },
    "asian": {
        "anime": "",
        "real": "east asian woman, korean chinese features, monolid or hooded almond eyes, smooth porcelain pale skin, small flat nose, straight black hair, asian bone structure, delicate petite features"
    },
    "russian": {
        "anime": "",
        "real": "russian slavic woman, eastern european, straight nose"
    },
    "italian": {
        "anime": "",
        "real": "italian mediterranean woman, southern european descent, warm olive tan skin, dark expressive almond-shaped eyes, dark wavy thick hair, roman nose, full sensual lips, mediterranean bone structure, NOT asian NOT oriental"
    },
    "latin": {
        "anime": "",
        "real": "latina hispanic woman, latin american descent, warm caramel tan skin, dark brown expressive eyes, full sensual lips, dark thick wavy hair, curvy features, hispanic bone structure, NOT asian NOT oriental NOT japanese"
    },
    "german": {
        "anime": "",
        "real": "german woman, northern european germanic descent, very fair pale skin, strong defined angular bone structure, prominent jaw, straight nose, light colored eyes blue or green, blonde or light brown hair, tall features, NOT asian NOT oriental NOT japanese"
    },
    "japanese": {
        "anime": "",
        "real": "japanese woman, pure japanese ethnicity, porcelain white pale skin, monolid or slight double eyelid almond eyes, small delicate nose, thin lips, straight silky black hair, petite refined features, japanese bone structure, asian"
    },
    "indian": {
        "anime": "",
        "real": "indian woman, south asian descent, warm brown caramel skin tone, large expressive dark brown eyes with thick lashes, full lips, dark black thick hair, elegant nose, distinctive south asian features, NOT east asian NOT japanese NOT chinese"
    },
    "arab": {
        "anime": "",
        "real": "arab middle eastern woman, arabian descent, warm olive tan skin, large dark almond-shaped eyes with natural kohl effect, thick dark arched eyebrows, elegant aquiline nose, full lips, dark wavy hair, exotic middle eastern beauty, NOT asian NOT japanese NOT chinese"
    }
}

body_type_to_prompt = {
    "anorexic slender body": "very thin slender figure, narrow hips and visible collarbones",
    "petite slim body": "petite slender figure and slim waist",
    "fit body": "slim athletic build, toned figure and fit physique",
    "curvy body": "curvy hourglass figure, wide hips and soft curves",
    "fat body": "plus size figure, full bodied and thick curves"
}

boobs_to_prompt = {
    "small breasts": "small breasts, modest chest",
    "beautiful breasts": "medium breasts, shapely bust",
    "big breasts": "big breasts, large bust",
    "huge breasts": "huge breasts, massive bust"
}

ass_to_prompt = {
    "small ass": "small tight butt",
    "fit ass": "toned athletic butt",
    "big round ass": "big round butt, thick thighs",
    "huge round ass": "huge round butt, very thick thighs"
}

haircut_to_prompt = {
    "straight haircut": {
        "anime": "long straight hair, silky smooth",
        "real": "long straight hair, sleek and shiny"
    },
    "braids haircut": {
        "anime": "twin braids, braided hair",
        "real": "elegant braids, braided hairstyle"
    },
    "curly hair": {
        "anime": "curly wavy hair, bouncy curls",
        "real": "natural curly hair, loose curls"
    },
    "hair in bun": {
        "anime": "hair bun, elegant updo",
        "real": "sleek hair bun, sophisticated updo"
    },
    "pixie haircut": {
        "anime": "short pixie cut, boyish hair",
        "real": "short pixie haircut, modern style"
    },
    "ponytail hair": {
        "anime": "high ponytail, swaying hair",
        "real": "sleek ponytail, flowing hair"
    },
    "two ponytails hair": {
        "anime": "twin tails, double ponytails",
        "real": "pigtails, playful double ponytails"
    },
    "bob haircut": {
        "anime": "bob haircut",
        "real": "bob haircut"
    }
}

eyes_to_prompt = {
    "brown": {
        "anime": "warm brown eyes",
        "real": "deep brown eyes"
    },
    "blue": {
        "anime": "bright blue eyes",
        "real": "striking blue eyes"
    },
    "green": {
        "anime": "bright green eyes",
        "real": "bright green eyes"
    },
    "grey": {
        "anime": "steel grey eyes",
        "real": "smoky grey eyes"
    },
    "purple": {
        "anime": "purple violet eyes",
        "real": "purple violet eyes"
    }
}

hair_color_to_prompt = {
    "black": "black hair",
    "brown": "dark brown hair",
    "blond": "golden blonde hair",
    "red": "red hair",
    "grey": "silver grey hair",
    "white": "white hair",
    "dark blue": "dark blue hair"
}

face_expression_by_personality = {
    "Заботливый": "gentle caring expression, warm smile",
    "Мудрец": "wise knowing expression, calm demeanor",
    "Невинный": "cute innocent expression, light blush",
    "Соблазнительница": "seductive expression, bedroom eyes, seductive look",
    "Доминант": "confident dominant expression, piercing gaze",
    "Покорный": "shy submissive expression, downcast eyes",
    "Любовник": "passionate expression, longing eyes",
    "Фанатик": "intense devoted expression, focused gaze",
    "Апатичный": "bored expression, distant look",
    "Доверенное лицо": "trustworthy expression, steady gaze"
}

skin_by_age = {
    "18": "smooth youthful skin",
    "25": "smooth skin",
    "35": "clear mature skin, refined features",
    "45": "mature skin, elegant features",
    "70": "mature skin with character, distinguished features"
}


default_wardrobe = {
    "casual": "simple casual outfit, jeans and top",
    "formal": "elegant evening dress",
    "sleepwear": "comfortable pajamas",
    "swimwear": "two-piece bikini",
    "underwear": "lingerie set",
    "nude": "naked, nude"
}


clothes_to_prompt = {
    "Бикини": "black two-piece bikini",
    "Голый": "naked, nude, no clothing",
    "Длинное платье": "long simple black evening dress with deep neckline",
    "Школьная форма": "japanese school uniform, serafuku, sailor collar, pleated skirt",
    "Свободная рубашка": "loose oversized white button-down shirt with professional jeans",
    "Костюм ведьмы": "witch costume, black witch hat, dark dress, mystical"
}


class CreateCharacterRequest(BaseModel):
    name: str
    style: Literal["anime", "real"]
    is_public: bool
    age: Literal["18", "25", "35", "45", "70"]
    nationality: Optional[Literal["american", "asian", "russian", "italian", "latin", "german", "japanese", "indian", "arab"]] = None
    eyes_color: Literal["brown", "blue", "green", "grey"]
    hair_color: Literal["black", "brown", "blond", "red", "grey", "white"]
    haircut: Literal["straight haircut", "braids haircut", "curly hair", "hair in bun", "pixie haircut", "ponytail hair", "two ponytails hair"]
    body_type: Literal["anorexic slender body", "petite slim body", "fit body", "curvy body", "fat body"]
    boobs_size: Literal["small breasts", "beautiful breasts", "big breasts", "huge breasts"]
    ass_size: Literal["small ass", "fit ass", "big round ass", "huge round ass"]
    clothing: str
    preferences: list[str]
    personality: Literal["Заботливый", "Мудрец", "Невинный", "Соблазнительница", "Доминант", "Покорный", "Любовник", "Фанатик", "Апатичный", "Доверенное лицо"]
    relationship: Literal["Падчерица", "Мачеха", "Любовница", "Одноклассник", "Коллега", "Учитель", "Девушка", "Друзья с привилегиями", "Жена", "Друг"]

    scenario: Optional[str] = None
    first_mes: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None

    def build_visual(self):
        if self.style == "real":
            return self._build_real_visual()
        elif self.style == "anime":
            return self._build_anime_visual()

    def _build_real_visual(self):
        visual = dict()
        visual["model_type"] = self.style
        visual["nationality"] = self.nationality
        visual["age"] = self.age
        visual["ass"] = self.ass_size
        visual["boobs"] = self.boobs_size
        visual["hair_color"] = self.hair_color
        visual["haircut"] = self.haircut
        visual["eye_color"] = self.eyes_color
        visual["wardrobe"] = {
            "casual": clothes_to_prompt[self.clothing],
            "underwear": "black lingerie set",
            "nude": "nothing, showing her naked body"
        }
        visual["llm_settings"] = {
            "preferences": self.preferences,
            "relationships": self.relationship
        }
        visual["body_type"] = self.body_type
        if self.avatar_url:
            visual["avatar"] = self.avatar_url

        return visual

    def _build_anime_visual(self):
        visual = dict()
        visual["model_type"] = self.style
        visual["age"] = self.age
        visual["ass"] = self.ass_size
        visual["boobs"] = self.boobs_size
        visual["hair_color"] = self.hair_color
        visual["haircut"] = self.haircut
        visual["eye_color"] = self.eyes_color
        visual["wardrobe"] = {
            "casual": clothes_to_prompt[self.clothing],
            "underwear": "black lingerie set",
            "nude": "nothing, showing her naked body"
        }
        visual["llm_settings"] = {
            "preferences": self.preferences,
            "relationships": self.relationship
        }
        visual["body_type"] = self.body_type
        if self.avatar_url:
            visual["avatar"] = self.avatar_url

        return visual
