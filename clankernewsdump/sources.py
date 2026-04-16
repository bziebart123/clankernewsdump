"""Source definitions for clankernewsdump."""

RSS_FEEDS = [
    # ---------- Personal blogs / thought leaders ----------
    ("Simon Willison", "https://simonwillison.net/atom/entries/", "blog"),
    ("Interconnects (Nathan Lambert)", "https://www.interconnects.ai/feed", "blog"),
    ("Import AI (Jack Clark)", "https://jack-clark.net/feed/", "blog"),
    ("Sebastian Raschka", "https://magazine.sebastianraschka.com/feed", "blog"),
    ("Lil'Log (Lilian Weng)", "https://lilianweng.github.io/index.xml", "blog"),
    ("Chip Huyen", "https://huyenchip.com/feed.xml", "blog"),
    ("Hamel Husain", "https://hamel.dev/index.xml", "blog"),
    ("Eugene Yan", "https://eugeneyan.com/rss/", "blog"),
    ("One Useful Thing (Ethan Mollick)", "https://www.oneusefulthing.org/feed", "blog"),
    ("Don't Worry About The Vase (Zvi)", "https://thezvi.substack.com/feed", "blog"),
    ("Gary Marcus", "https://garymarcus.substack.com/feed", "blog"),
    ("Astral Codex Ten (Scott Alexander)", "https://www.astralcodexten.com/feed", "blog"),
    ("Gwern", "https://gwern.net/index.xml", "blog"),
    ("Exponential View (Azeem Azhar)", "https://www.exponentialview.co/feed", "blog"),
    ("Strange Loop Canon (Rohit Krishnan)", "https://www.strangeloopcanon.com/feed", "blog"),
    ("AI Snake Oil (Narayanan/Kapoor)", "https://www.aisnakeoil.com/feed", "blog"),
    ("The Algorithmic Bridge (Alberto Romero)", "https://www.thealgorithmicbridge.com/feed", "blog"),
    ("AI Supremacy (Michael Spencer)", "https://aisupremacy.substack.com/feed", "blog"),
    ("Marginal Revolution", "https://marginalrevolution.com/feed", "blog"),
    ("Stratechery Free (Ben Thompson)", "https://stratechery.com/feed/", "blog"),
    ("Platformer (Casey Newton)", "https://www.platformer.news/feed", "blog"),
    ("Benedict Evans", "https://www.ben-evans.com/benedictevans?format=rss", "blog"),
    ("Matt Turck", "https://mattturck.com/feed/", "blog"),
    ("Last Week in AI", "https://lastweekin.ai/feed", "blog"),

    # ---------- Newsletters / aggregators ----------
    ("The Batch (Andrew Ng)", "https://www.deeplearning.ai/the-batch/feed/", "newsletter"),
    ("Latent Space", "https://www.latent.space/feed", "newsletter"),
    ("Ben's Bites", "https://bensbites.beehiiv.com/feed", "newsletter"),
    ("TLDR AI", "https://tldr.tech/api/rss/ai", "newsletter"),
    ("Data Machina", "https://datamachina.substack.com/feed", "newsletter"),
    ("The Gradient", "https://thegradient.pub/rss/", "newsletter"),
    ("MIT Tech Review (AI)", "https://www.technologyreview.com/topic/artificial-intelligence/feed", "newsletter"),
    ("The Neuron", "https://www.theneurondaily.com/feed", "newsletter"),
    ("AI Breakfast", "https://aibreakfast.beehiiv.com/feed", "newsletter"),

    # ---------- Lab / org announcements ----------
    ("Anthropic News", "https://www.anthropic.com/news/rss.xml", "lab"),
    ("OpenAI Blog", "https://openai.com/blog/rss.xml", "lab"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", "lab"),
    ("Google Research", "https://research.google/blog/rss/", "lab"),
    ("Meta AI", "https://ai.meta.com/blog/rss/", "lab"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml", "lab"),
    ("Mistral AI", "https://mistral.ai/news/feed.xml", "lab"),
    ("Cohere", "https://cohere.com/blog/rss.xml", "lab"),
    ("Allen AI (AI2)", "https://allenai.org/blog/rss", "lab"),
    ("EleutherAI", "https://blog.eleuther.ai/index.xml", "lab"),
    ("NVIDIA Developer", "https://developer.nvidia.com/blog/feed/", "lab"),
    ("Apple ML Research", "https://machinelearning.apple.com/rss.xml", "lab"),
    ("Stanford HAI", "https://hai.stanford.edu/news/rss.xml", "lab"),
    ("Berkeley BAIR", "https://bair.berkeley.edu/blog/feed.xml", "lab"),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/", "lab"),

    # ---------- Podcasts / YouTube (RSS) ----------
    ("Dwarkesh Podcast", "https://www.dwarkeshpatel.com/feed", "podcast"),
    ("No Priors", "https://feeds.transistor.fm/no-priors-artificial-intelligence-machine-learning-technology-startups", "podcast"),
    ("Cognitive Revolution", "https://feeds.transistor.fm/the-cognitive-revolution-how-ai-changes-everything", "podcast"),
    ("Latent Space Pod", "https://api.substack.com/feed/podcast/1084089.rss", "podcast"),
    ("Machine Learning Street Talk", "https://anchor.fm/s/1e4a0eac/podcast/rss", "podcast"),
    ("TWIML AI Podcast", "https://feeds.megaphone.fm/MLN2155636147", "podcast"),
    ("Practical AI", "https://changelog.com/practicalai/feed", "podcast"),
    ("Hard Fork (NYT)", "https://feeds.simplecast.com/l2i9YnTd", "podcast"),
    ("Gradient Dissent", "https://feeds.soundcloud.com/users/soundcloud:users:612300365/sounds.rss", "podcast"),
    ("Lex Fridman Podcast", "https://lexfridman.com/feed/podcast/", "podcast"),
    ("Eye on AI", "https://eyeonai.libsyn.com/rss", "podcast"),

    # ---------- News outlets ----------
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "news"),
    ("The Verge AI", "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml", "news"),
    ("Ars Technica AI", "https://arstechnica.com/ai/feed/", "news"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/", "news"),
    ("Wired AI", "https://www.wired.com/feed/tag/ai/latest/rss", "news"),
    ("404 Media", "https://www.404media.co/rss/", "news"),
    ("Semafor Tech", "https://www.semafor.com/rss/section/technology", "news"),
]

# Reddit subs (public .json endpoints)
SUBREDDITS = [
    "LocalLLaMA",
    "MachineLearning",
    "singularity",
    "OpenAI",
    "ClaudeAI",
    "ChatGPTCoding",
    "ArtificialIntelligence",
    "agi",
]

# Hacker News Algolia query terms
HN_QUERIES = [
    "LLM",
    "Claude",
    "GPT-5",
    "Anthropic",
    "OpenAI",
    "Gemini",
    "Llama",
    "AI agent",
    "transformer",
    "diffusion model",
]

# arXiv categories
ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL"]
