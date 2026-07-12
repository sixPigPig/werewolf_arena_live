import classic12SelectedCard from "../../assets/rule-cards/classic-12-selected.png";
import classic12UnselectedCard from "../../assets/rule-cards/classic-12-unselected.png";
import classic8SelectedCard from "../../assets/rule-cards/classic-8-selected.png";
import classic8UnselectedCard from "../../assets/rule-cards/classic-8-unselected.png";
import social8SelectedCard from "../../assets/rule-cards/social-8-selected.png";
import social8UnselectedCard from "../../assets/rule-cards/social-8-unselected.png";
import starter6SelectedCard from "../../assets/rule-cards/starter-6-selected.png";
import starter6UnselectedCard from "../../assets/rule-cards/starter-6-unselected.png";

type RuleCardImages = {
  selected: string;
  unselected: string;
};

const ruleCardImagesById: Partial<Record<string, RuleCardImages>> = {
  classic_8: {
    selected: classic8SelectedCard,
    unselected: classic8UnselectedCard,
  },
  starter_6: {
    selected: starter6SelectedCard,
    unselected: starter6UnselectedCard,
  },
  social_8: {
    selected: social8SelectedCard,
    unselected: social8UnselectedCard,
  },
  classic_12_seer_witch_hunter_idiot: {
    selected: classic12SelectedCard,
    unselected: classic12UnselectedCard,
  },
};

export function getLobbyRuleCardImage(
  ruleSetId: string,
  isSelected: boolean,
): string | null {
  const images = ruleCardImagesById[ruleSetId];
  if (!images) return null;
  return isSelected ? images.selected : images.unselected;
}
