# Lex V2 bot config (photo-search-bot, en_US)

## Slot type: KeywordType
- Slot value resolution: **Expand values** (so words not in the list are still captured)
- Sample values (one per line):
dog, dogs, cat, cats, tree, trees, bird, birds, person, people, car, flower, beach, mountain,
sky, water, food, building, city, park, ball, sunset, snow, grass, child, animal, bicycle, phone,
laptop, book, chair, table, horse, boat, bridge, road, house, sam, sally, golden retriever

## Intent: SearchIntent
Slots (both **optional**, slot type KeywordType):
- keyword1   prompt: "What do you want to search for?"
- keyword2   prompt: "Anything else?"

Sample utterances (paste one per line):
```
{keyword1}
{keyword1} and {keyword2}
show me {keyword1}
show me {keyword1} and {keyword2}
show me photos of {keyword1}
show me photos of {keyword1} and {keyword2}
show me photos with {keyword1}
show me photos with {keyword1} in them
show me photos with {keyword1} and {keyword2}
show me photos with {keyword1} and {keyword2} in them
show me pictures of {keyword1}
show me pictures of {keyword1} and {keyword2}
photos of {keyword1}
photos of {keyword1} and {keyword2}
pictures of {keyword1}
pictures with {keyword1} and {keyword2}
images of {keyword1}
find {keyword1}
find {keyword1} and {keyword2}
find photos of {keyword1}
search for {keyword1}
search for {keyword1} and {keyword2}
i want to see {keyword1}
i want to see {keyword1} and {keyword2}
{keyword1} or {keyword2}
show me {keyword1} or {keyword2}
```
