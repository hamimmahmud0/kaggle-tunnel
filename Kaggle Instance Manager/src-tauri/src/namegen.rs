//! Reddit-style auto-name generator for group names.
//! Generates names like ``QuietFox_7291`` or ``HappyPenguin_3842``.

const ADJECTIVES: &[&str] = &[
    "Ancient","Autumn","Azure","Bitter","Blind","Blue","Bold","Brave",
    "Bright","Calm","Clever","Cold","Cool","Cozy","Crimson","Curly",
    "Cute","Damp","Dawn","Deep","Dense","Dim","Dry","Dusty","Eager",
    "Early","Easy","Empty","Faint","Fair","Fancy","Fast","Fat","Fine",
    "Flat","Fleet","Fresh","Frosty","Funny","Gentle","Glad","Grand",
    "Gray","Great","Green","Happy","Harsh","Hazy","Heavy","Hidden",
    "Holy","Hot","Humble","Hungry","Icy","Jolly","Junior","Kind",
    "Lame","Large","Late","Lazy","Light","Limp","Little","Lively",
    "Lone","Long","Loud","Low","Lucky","Lunar","Major","Mellow",
    "Mild","Minor","Misty","Mixed","Modern","Muddy","Mute","Narrow",
    "Neat","New","Noble","Nordic","Odd","Old","Pale","Petite","Plain",
    "Plump","Polite","Poor","Proud","Pure","Purple","Quaint","Quick",
    "Quiet","Rapid","Rare","Red","Rich","Rough","Royal","Rustic","Sad",
    "Safe","Salty","Scaly","Shady","Shallow","Sharp","Shiny","Short",
    "Shy","Silent","Silly","Simple","Skinny","Slim","Slow","Small",
    "Smart","Smooth","Soft","Solar","Solid","Sour","Sparky","Square",
    "Steady","Steep","Stiff","Still","Stout","Strange","Strict",
    "Sturdy","Subtle","Sudden","Sunny","Super","Sweet","Swift","Tall",
    "Tame","Tart","Tender","Tiny","Tough","Tricky","Tropical","True",
    "Turbo","Twin","Ultra","Vague","Vast","Velvet","Vivid","Warm",
    "Wavy","Weak","Wet","Wild","Willing","Wise","Witty","Woolly",
    "Young","Zany","Zealous","Zesty",
];

const NOUNS: &[&str] = &[
    "Alpaca","Ant","Ape","Apple","Badger","Bass","Bat","Bear","Beaver",
    "Bee","Bird","Bison","Bobcat","Bunny","Camel","Cat","Caterpillar",
    "Cheetah","Chicken","Cobra","Cod","Cougar","Cow","Coyote","Crab",
    "Crane","Cricket","Crow","Deer","Dingo","Dog","Dolphin","Donkey",
    "Dove","Dragon","Duck","Eagle","Eel","Elk","Emu","Falcon","Ferret",
    "Finch","Fish","Flamingo","Fly","Fox","Frog","Gator","Gazelle",
    "Gecko","Gibbon","Giraffe","Goat","Goose","Gorilla","Gull","Hare",
    "Hawk","Hen","Heron","Hippo","Horse","Hound","Hyena","Ibex","Ibis",
    "Impala","Jackal","Jaguar","Jay","Jelly","Kangaroo","Koala","Koi",
    "Lemur","Leopard","Lion","Llama","Lobster","Lynx","Macaw","Mallard",
    "Mantis","Marten","Mink","Mole","Monkey","Moose","Mouse","Mule",
    "Newt","Ocelot","Octopus","Opossum","Otter","Owl","Ox","Panda",
    "Panther","Parrot","Peacock","Pegasus","Penguin","Pheasant","Pig",
    "Pigeon","Pike","Pony","Puma","Puppy","Rabbit","Raccoon","Ram",
    "Rat","Raven","Rhino","Robin","Rook","Salmon","Saw","Seal","Shark",
    "Sheep","Shrimp","Skunk","Sloth","Snail","Snake","Sparrow","Spider",
    "Squid","Squirrel","Stag","Stoat","Stork","Swan","Tahr","Tapir",
    "Tiger","Toad","Trout","Tuna","Turkey","Turtle","Viper","Vulture",
    "Wallaby","Walrus","Wasp","Weasel","Whale","Wolf","Wombat","Worm",
    "Wren","Yak","Zebra","Zorro",
];

/// Generate a Reddit-style auto-name like ``QuietFox_7291``.
pub fn generate() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let seed = SystemTime::now()
        .duration_since(UNIX_EPOCH).unwrap_or_default().as_nanos();
    let mut rng = seed as u64;
    let mut next = || -> usize {
        rng = rng.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        (rng >> 33) as usize
    };
    format!("{}{}_{:04}",
        ADJECTIVES[next() % ADJECTIVES.len()],
        NOUNS[next() % NOUNS.len()],
        next() % 10000)
}
