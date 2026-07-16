# Project Valhalla — Roadmap

Цей файл зберігає погоджені ідеї для наступних етапів розвитку. Він не означає, що функції вже реалізовані.

Основні обмеження залишаються незмінними:

- один `app.py`;
- одна вручну редагована `database.json`;
- один активний локальний `workflow.json`;
- CLI та інтерактивний `launcher.sh`;
- без FaceID, IPAdapter, PuLID та architecture-specific identity pipelines;
- повна сумісність із різними checkpoint families через захоплений workflow;
- лише дорослі моделі віком 21–22 роки;
- приватні локації та solo scenes.

## P0 — Storyboard Director

Implemented MVP foundation:

- [x] Resolve the complete batch before rendering.
- [x] Keep a fixed photoshoot context in every planned shot.
- [x] Provide an interactive Director's Desk before any GPU job.
- [x] Support full-storyboard reroll, single-shot reroll, stage selection, and compatible pose/action/expression selection.
- [x] Add Casting & Set Design for subject, wardrobe, location, surface, mood, and photography style.
- [x] Add constrained subject, wardrobe, interior, and surface remixing with category locks.
- [x] Use searchable `fzf` selectors on every fixed-choice launcher and Director screen, with a numbered-menu fallback.
- [x] Prevent manually edited photoshoot stages from reversing progression.
- [x] Keep automatic behavior available without interactive review.

- [x] Планувати всю фотосесію до початку генерації, а не резолвити кадри як майже незалежні сцени.
- [x] Зберігати continuity для моделі, outfit, кольорів, інтер’єру, mood і lighting family.
- [ ] Планувати послідовність stage, framing, camera angle, pose family, action family та expression intensity.
- [ ] Формувати редакційну арку: establishing → medium → reveal → nude → explicit plateau.
- [ ] Для `xxx-only` планувати всю серію відразу як explicit storyboard.
- [ ] Передавати готовий storyboard у resolver без випадкового руйнування запланованої структури.
- [x] Зупиняти batch до GPU-запуску, якщо storyboard неможливо повністю розв’язати.

Критерії готовності:

- однаковий prompt seed відтворює ідентичний storyboard;
- кожен кадр має пояснювану роль у серії;
- progression не рухається назад;
- сусідні кадри не дублюють композицію без явної причини.

## P0 — Camera grammar

- [ ] Додати до `database.json` секції `shot_sizes`, `camera_angles`, `framings` і `focus_targets`.
- [ ] Підтримати full body, three-quarter, medium, portrait, torso close-up, breast close-up, intimate macro та rear close-up.
- [ ] Підтримати eye-level, low angle, high angle, overhead, rear і over-the-shoulder camera angles.
- [ ] Додати centered, diagonal editorial, symmetrical, tight crop та environmental framing.
- [ ] Узгоджувати camera grammar із pose, action, furniture, visibility та exposure stage.
- [ ] Заборонити несумісні комбінації на кшталт intimate macro + full-body framing.
- [ ] Гарантувати rear angle для rear-display recipes і відповідний close-up для intimate actions.

Критерії готовності:

- кожна resolved scene має shot size, angle, framing і focus target;
- validator знаходить недосяжні або несумісні camera records;
- dry-run на 5 000 кадрів не створює framing conflicts.

## P0 — Weighted shuffle bags і diversity

- [ ] Замінити незалежний weighted random для важливих категорій на weighted shuffle bags.
- [ ] Не повторювати pose, action, expression, prop, shot size або angle до вичерпання сумісного pool.
- [ ] Вести окремі bags для кожної фотосесії та кожного stage family.
- [ ] Дозволити повтор після вичерпання pool, але уникати однакових сусідніх кадрів.
- [ ] Додати diversity score для всього storyboard.
- [ ] Штрафувати повтори pose family, action family, camera angle, shot size, prop і furniture surface.
- [ ] Не штрафувати навмисно зафіксовані identity, outfit, location, palette та lighting family.

Критерії готовності:

- усі доступні plateau recipes використовуються до повторення;
- немає однакових pose/action pairs у сусідніх кадрах;
- один seed повністю відтворює порядок shuffle bags.

## P0 — Deterministic inference-seed sequence

- [ ] Зберегти поточні `fixed` і `random per image` режими.
- [ ] Додати третю стратегію `deterministic sequence`.
- [ ] Отримувати seed кадру з base seed, photoshoot index і shot index стабільним hash-алгоритмом.
- [ ] Не використовувати Python `hash()`, оскільки він не стабільний між процесами.
- [ ] Друкувати base seed та effective shot seed.
- [ ] Додати вибір стратегії до launcher.
- [ ] Зберегти буквальну незмінність seed у поточному fixed mode.

Критерії готовності:

- повторний запуск із тим самим base seed відтворює всі inference seeds;
- різні кадри отримують різні seeds;
- різні фотосесії одного batch не перетинаються за seed sequence.

## P1 — Prompt Compiler v2

- [ ] Перебудувати prompt у порядку фактичного пріоритету для diffusion model.
- [ ] Порядок: solo/adult constraint → camera → pose/action → visible anatomy → identity → visible garments → location → expression → light/quality.
- [ ] Не дублювати жодну human trait у кількох prompt-блоках.
- [ ] Ввести `compact`, `balanced` і `detailed` prompt profiles.
- [ ] Додати приблизний prompt/token budget для кожного profile.
- [ ] Скорочувати найменш важливі fragments, не викидаючи pose/action та adult constraints.
- [ ] Зробити негативні prompts stage-specific.
- [ ] Прибрати нерелевантні negatives для fashion stages.
- [ ] Посилювати censorship/coverage negatives лише для explicit stages.
- [ ] Додати prompt lint: duplicate subject descriptions, conflicting framing, contradictory clothing та repeated fragments.

Критерії готовності:

- action і pose завжди знаходяться у високопріоритетній частині prompt;
- compact profile не втрачає model identity і stage semantics;
- compiler output не містить повторних trait fragments;
- одна resolved scene компілюється детерміновано.

## P1 — Compact identity fingerprint

- [ ] Відокремити повний `model_signature` від короткого diffusion identity fingerprint.
- [ ] Включати у fingerprint лише найбільш візуально значущі face, hair, skin та body traits.
- [ ] Вибирати 1–2 distinctive traits для кожної моделі.
- [ ] Додати каталог distinctive beauty marks та інших стабільних facial anchors.
- [ ] Не використовувати batch-temporal phrases, які diffusion model може інтерпретувати як кілька subjects.
- [x] Завжди зберігати компактний `solo adult woman` і `single subject` anchor на початку prompt.
- [ ] Зберегти strengthened duplicate-person negatives.

Критерії готовності:

- fingerprint незмінний у межах фотосесії;
- traits згадуються у prompt лише один раз;
- повний model signature залишається доступним у console output.

## P1 — Dynamic location surfaces

- [ ] Фіксувати interior, palette, mood, time of day і lighting family на фотосесію.
- [ ] Не фіксувати одне furniture на всю серію.
- [ ] Вибирати різні сумісні surfaces у межах того самого interior.
- [ ] Додати zones: bed, bed edge, wall, vanity, window, rug, sofa, chair, pool edge, garden surface.
- [ ] Прив’язати poses і shot sizes до surface capabilities.
- [ ] Не змінювати room identity під час переходу між surfaces.

Критерії готовності:

- photoshoot зберігає одну впізнавану локацію;
- furniture/surface змінюється без логічних конфліктів;
- ванна, басейн, спальня та outdoor surfaces не змішуються.

## P1 — Exact garment transitions

- [ ] Порівнювати visible garment slots поточного і попереднього stage.
- [ ] Обчислювати exact removed/revealed slots.
- [ ] Вибирати undressing action, що відповідає конкретному garment type.
- [ ] Додати actions для zipper, buttons, straps, bra hooks, skirt, dress, panties, stockings і footwear.
- [ ] Підтримати intentional retained garments: stockings, heels, garter, accessories.
- [ ] Не описувати зняття garment, якого немає або який уже знятий.
- [ ] Не дозволяти одягу повертатися у progressive photoshoot.

Критерії готовності:

- кожна undressing action відповідає state diff;
- dry-run не містить impossible removal actions;
- visible anatomy з’являється лише після відповідного transition.

## P1 — XXX plateau recipes

- [ ] Замінити лише три широкі plateau kinds на каталог конкретних recipes.
- [ ] Додати rear standing, rear all-fours, bent-over, legs-up, legs-wide, intimate macro, breast focus, різні hands-only manual stimulation та climax recipes.
- [ ] Для кожного recipe визначити pose tags, action tags, framing, angle, visibility, furniture, prop probability та expression intensity.
- [ ] Додати configurable weights у `database.json`.
- [ ] Дозволити користувачу вимикати окремі recipe families.
- [ ] Рівномірно планувати активні recipe families у photoshoot plateau.
- [ ] У `random --xxx-only` використовувати weighted shuffle, а не незалежні повтори.

Критерії готовності:

- кожен активний recipe досяжний;
- recipe не збирається з несумісних pose/action/camera components;
- masturbation recipes використовують лише руки й не додають сторонніх предметів;
- expression завжди відповідає інтенсивності action.

## P1 — Intensity scale

- [ ] Додати спільну шкалу `fashion`, `sensual`, `erotic`, `nude`, `explicit`, `peak`.
- [ ] Позначити intensity для poses, actions, expressions, camera framing і lighting.
- [ ] Заборонити різкі несумісності intensity.
- [ ] Планувати плавне зростання intensity у progressive photoshoot.
- [ ] У `xxx-only` починати з `explicit`, а завершувати `peak`.

Критерії готовності:

- expression не слабша або не сильніша за action без навмисного правила;
- progressive intensity не рухається назад;
- peak shots мають відповідні framing, action та expression.

## P2 — Команда `plan`

- [ ] Додати `python app.py plan` з тими самими mode/seed/count options.
- [ ] Показувати компактну таблицю storyboard без повних prompts.
- [ ] Виводити stage, shot size, angle, pose, action, prop, expression і surface.
- [ ] Додати `--verbose` для повного resolved prompt.
- [ ] Додати запуск `plan` до launcher.

Критерії готовності:

- storyboard легко перевірити до GPU generation;
- `plan` і `generate` з однаковими seeds будують однакові сцени.

## P2 — Команди `validate` і `stats`

- [ ] Додати окрему `validate` command.
- [ ] Перевіряти всі templates багаторазовим resolver stress test.
- [ ] Перевіряти всі camera combinations і plateau recipes.
- [ ] Знаходити unreachable IDs.
- [ ] Знаходити garments, poses, actions, expressions і props, які не використовує жоден recipe/template.
- [ ] Додати `stats` command із counts, tags, coverage і candidate pool sizes.
- [ ] Додати обидві команди до launcher.

Критерії готовності:

- production validation не потребує ручного redirect великого dry-run output;
- exit code ненульовий при будь-якому structural або reachability conflict.

## P2 — HTML contact sheet

- [ ] Створювати директорію на кожну фотосесію.
- [ ] Генерувати локальний `index.html` без додаткових Python dependencies.
- [ ] Показувати thumbnails, shot index, stage, pose/action та seeds.
- [ ] Додати model signature та resolved prompt у collapsible details.
- [ ] Додати готову команду повторного запуску фотосесії.
- [ ] Не створювати JSONL.
- [ ] Зробити contact sheet configurable у settings.

Критерії готовності:

- серію можна оцінити одним відкриттям HTML;
- metadata достатньо для ручного відтворення кадру.

## P2 — Retry policy і shot regeneration

- [ ] Додати configurable retry count для HTTP, ComfyUI та missing-output failures.
- [ ] Повторювати той самий resolved prompt із новим inference seed, якщо strategy це дозволяє.
- [ ] Не змінювати storyboard під час технічного retry.
- [ ] Додати команду regeneration конкретного shot за printed metadata.
- [ ] Зупиняти batch після вичерпання retries.
- [ ] Не додавати image-quality detector або зовнішню vision model у межах цієї задачі.

Критерії готовності:

- transient failure не втрачає всю фотосесію;
- retry поведінка видима й пояснювана в console output.

## Порядок майбутньої реалізації

1. Storyboard Director data model.
2. Camera grammar та database records.
3. Shuffle bags і diversity score.
4. Deterministic inference-seed sequence.
5. Dynamic location surfaces.
6. Prompt Compiler v2 та budgets.
7. Compact identity fingerprint.
8. Exact garment transitions.
9. Plateau recipes та intensity scale.
10. `plan`, `validate`, `stats`.
11. HTML contact sheet.
12. Retry та shot regeneration.

## Загальні regression tests

- [ ] Однаковий prompt seed відтворює повний storyboard і prompt sequence.
- [ ] Deterministic inference strategy відтворює всі shot seeds.
- [ ] Photoshoot зберігає одну модель, outfit identity, location identity та palette.
- [ ] Random mode перебудовує контекст для кожного кадру.
- [ ] Progressive stages та intensity ніколи не рухаються назад.
- [ ] XXX-only не містить covered, lingerie або transition stages.
- [ ] Жодна scene не має більше одного персонажа у positive prompt.
- [ ] Жодна human trait не дублюється у compiled prompt.
- [ ] Жоден garment не знімається двічі або після свого зникнення.
- [ ] Жоден sexual toy не існує у selectable database, positive prompt або resolved scene.
- [ ] Усі outdoor locations приватні та відокремлені від публічних місць.
- [ ] Stress test на 10 000 planned scenes проходить без resolver conflict.
- [ ] `python3 -m py_compile app.py`, JSON validation, shell syntax і `git diff --check` проходять.
