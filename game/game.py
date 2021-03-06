import sys
from itertools import chain
from threading import Lock

import numpy as np

if sys.version_info[0] == 2:
    import deck
    import player as player_m
    import field
    range = xrange
elif sys.version_info[0] == 3:
    import game.deck as deck
    import game.player as player_m
    import game.field as field


class Game:
    """A skeleton offering the most relevant functions for durak.

    Also keeps track of the features.
    """

    def __init__(
            self, names, deck_size=52, hand_size=6, trump_suit=None,
            feature_type=2, buffer_features=False, only_ais=False):
        """Initialize a game of durak with the given names, a card
        deck of the given size and hands of the given size.

        If given, trump_suit determines the trump suit for the game,
        only_ais determines whether only AIs play in the game and
        feature_type determines which type of feature vector to
        construct.
        1 for a feature vector of constant size using indices from the
          player to determine a card's location.
          Represents the whole game.
        2 for a feature vector of varying size using binary values for
          whether a card is in a player's hand.
        3 for a feature vector of constant size with very limited
          information. Also using indices to determine card locations.
        """
        assert feature_type in [1, 2, 3], 'Feature type must be 1, 2 or 3'
        assert not (deck_size > 52
                and (feature_type == 2 or feature_type == 3)), ('Feature type '
                '2 and 3 are only supported for deck sizes without duplicates '
                '(52 or less)')
        self.orig_deck_size = deck_size
        if buffer_features:
            self.orig_deck_size = 52
        self.deck = deck.Deck(deck_size, trump_suit, buffer_features)
        self.hand_size = hand_size
        self.only_ais = only_ais
        self.feature_type = feature_type
        self.feature_lock = Lock()
        self.player_count = len(names)
        assert self.player_count > 1 and self.player_count < 8, \
                'Player count does not make sense'
        if self.only_ais:
            self.kraudia_ix = -1
            self.indices_from = [self.calculate_indices_from(ix)
                    for ix in range(self.player_count)]
        else:
            self.kraudia_ix = names.index('Kraudia')
            self.indices_from_kraudia = self.calculate_indices_from()
        self.field = field.Field()
        self.defender_ix = -1
        # feature initialization
        if feature_type == 1:
            # deck_size features for each card's location
            #   -4 is bottom trump, -3 is unknown, -2 is out of game
            #   and -1 is on field
            #   >= 0 are indices from the player's position
            # 1 feature for which suit next player could not defend
            #   num_suit of card (-1 if unknown)
            # 1 feature for whether the defending player checks
            #   binary
            # 1 feature for deck size
            #   size of deck
            if self.only_ais:
                self.features = np.full((self.player_count,
                        self.orig_deck_size + 3), -3, dtype=np.int8)
                self.features[:, self.deck.bottom_trump.index] = -4
                self.features[:, self.orig_deck_size] = -1
                self.features[:, self.orig_deck_size + 1] = 0
                self.features[:, self.orig_deck_size + 2] = self.deck.size
                if buffer_features:
                    for num_suit in range(4):
                        for num_value in range(13 - self.deck.cards_per_suit):
                            self.features[:, num_value + num_suit * 13] = -2
            else:
                self.features = np.full(self.orig_deck_size + 3, -3,
                        dtype=np.int8)
                self.features[self.deck.bottom_trump.index] = -4
                self.features[self.orig_deck_size] = -1
                self.features[self.orig_deck_size + 1] = 0
                self.features[self.orig_deck_size + 2] = self.deck.size
                if buffer_features:
                    for num_suit in range(4):
                        for num_value in range(13 - self.deck.cards_per_suit):
                            self.features[num_value + num_suit * 13] = -2
        elif feature_type == 2:
            # (player_count + 2) * deck_size features for whether a
            # player has a card, it is on the field or out of the game
            #   binary
            # 1 feature for which suit next player could not defend
            #   num_suit of suit (-1 if unknown)
            # 1 feature for value of bottom trump
            #   num_value of card
            # 1 feature for whether the defending player checks
            #   binary
            # 1 feature for deck size
            #   size of deck
            self.field_index = self.player_count * self.orig_deck_size
            self.out_index = self.field_index + self.orig_deck_size
            self.after_index = self.out_index + self.orig_deck_size
            if self.only_ais:
                self.calculate_feature_indices()
                self.features = np.zeros((self.player_count,
                        self.after_index + 4), dtype=np.int8)
                self.features[:, self.after_index] = -1
                self.features[:, self.after_index + 1] = \
                        self.deck.bottom_trump.num_value
                self.features[:, self.after_index + 3] = self.deck.size
                if buffer_features:
                    for num_suit in range(4):
                        card_ix = lambda num_value: num_value + num_suit * 13
                        for num_value in range(13 - self.deck.cards_per_suit):
                            self.features[:, self.out_index
                                    + card_ix(num_value)] = 1
            else:
                self.calculate_feature_indices()
                self.features = np.zeros(self.after_index + 4, dtype=np.int8)
                self.features[self.after_index] = -1
                self.features[self.after_index + 1] = \
                        self.deck.bottom_trump.num_value
                self.features[self.after_index + 3] = self.deck.size
                if buffer_features:
                    for num_suit in range(4):
                        card_ix = lambda num_value: num_value + num_suit * 13
                        for num_value in range(13 - self.deck.cards_per_suit):
                            self.features[self.out_index
                                    + card_ix(num_value)] = 1
        else:
            # 5 * deck_size features for whether a player (only agent, its next
            # neighbour and its previous neighbour) has a card, it is on the
            # field or out of the game
            #   binary
            # 1 feature for which suit next player could not defend
            #   num_suit of suit (-1 if unknown)
            # 1 feature for value of bottom trump
            #   num_value of card
            # 1 feature for whether the defending player checks
            #   binary
            # 1 feature for deck size
            #   size of deck
            self.field_index = 3 * self.orig_deck_size
            self.out_index = self.field_index + self.orig_deck_size
            self.after_index = self.out_index + self.orig_deck_size
            self.prev_neighbour_index = 2 * self.orig_deck_size
            if self.only_ais:
                self.features = np.zeros((self.player_count,
                        self.after_index + 4), dtype=np.int8)
                self.features[:, self.after_index] = -1
                self.features[:, self.after_index + 1] = \
                        self.deck.bottom_trump.num_value
                self.features[:, self.after_index + 3] = self.deck.size
                if buffer_features:
                    for num_suit in range(4):
                        card_ix = lambda num_value: num_value + num_suit * 13
                        for num_value in range(13 - self.deck.cards_per_suit):
                            self.features[:, self.out_index
                                    + card_ix(num_value)] = 1
            else:
                self.features = np.zeros(self.after_index + 4, dtype=np.int8)
                self.features[self.after_index] = -1
                self.features[self.after_index + 1] = \
                        self.deck.bottom_trump.num_value
                self.features[self.after_index + 3] = self.deck.size
                if buffer_features:
                    for num_suit in range(4):
                        card_ix = lambda num_value: num_value + num_suit * 13
                        for num_value in range(13 - self.deck.cards_per_suit):
                            self.features[self.out_index
                                    + card_ix(num_value)] = 1
        self.players = [self.init_player(ix, name)
                for ix, name in enumerate(names)]

    def init_player(self, ix, name):
        """Initialize a player with the given index and name."""
        new_player = player_m.Player(name, self.deck.take(self.hand_size))
        # update features
        if self.only_ais:
            if self.feature_type == 1:
                for card in new_player.cards:
                    self.features[ix, card.index] = 0
            else:
                for card in new_player.cards:
                    self.features[ix, card.index] = 1
        elif ix == self.kraudia_ix:
            if self.feature_type == 1:
                for card in new_player.cards:
                    self.features[card.index] = 0
            else:
                for card in new_player.cards:
                    self.features[card.index] = 1
        return new_player

    def find_beginner(self):
        """Return the index of the player with the lowest trump and
        the card or a random index and the bottom trump if no player
        has a trump in hand.

        Also update the defender index.
        """
        mini = 13
        beginner_ix = np.random.randint(self.player_count)
        beginner_card = self.deck.bottom_trump
        for ix, player in enumerate(self.players):
            if (mini == 2 or self.deck.bottom_trump.num_value == 2
                    and mini == 3):
                break
            for card in player.cards:
                if (card.num_suit == self.deck.num_trump_suit
                        and card.num_value < mini):
                    mini = card.num_value
                    beginner_ix = ix
                    beginner_card = card
                    if (mini == 2 or self.deck.bottom_trump.num_value == 2
                            and mini == 3):
                        break
        self.defender_ix = beginner_ix + 1
        if self.defender_ix == self.player_count:
            self.defender_ix = 0
        return beginner_ix, beginner_card

    def attack(self, attacker_ix, cards):
        """Attack the defender with the attacker's given cards."""
        assert attacker_ix < self.player_count, 'Attacker does not exist'
        attacker = self.players[attacker_ix]
        assert not self.exceeds_field(cards), ('Number of attack cards '
                'exceeds allowed number')
        assert len(cards) <= len(self.players[self.defender_ix].cards), \
                'Defender does not have that many cards'
        for card in cards:
            assert card in attacker.cards, ('Attacker does not have one of '
                    'the cards')
        if self.field.is_empty():
            assert deck.same_value(cards), ('Cards must have the same value '
                    'for initial attack.')
        else:
            assert self.field.values_on_field(cards), ("One of the cards' "
                    "values is not on the field")
        attacker.attack(cards)
        self.field.attack(cards)
        # update features
        if self.only_ais:
            if self.feature_type == 1:
                self.feature_lock.acquire()
                for card in cards:
                    self.features[:, card.index] = -1
                self.feature_lock.release()
            elif self.feature_type == 2:
                self.feature_lock.acquire()
                for card in cards:
                    self.features[:, self.field_index + card.index] = 1
                    for ix in range(self.player_count):
                        self.features[ix, self.feature_indices[ix][attacker_ix]
                                + card.index] = 0
                self.feature_lock.release()
            else:
                prev_neighbour_ix = self.prev_neighbour(attacker_ix)
                next_neighbour_ix = self.next_neighbour(attacker_ix)
                self.feature_lock.acquire()
                for card in cards:
                    self.features[:, self.field_index + card.index] = 1
                    self.features[attacker_ix, card.index] = 0
                    self.features[prev_neighbour_ix, self.orig_deck_size
                            + card.index] = 0
                    self.features[next_neighbour_ix, self.prev_neighbour_index
                            + card.index] = 0
                self.feature_lock.release()
        elif self.kraudia_ix >= 0:
            if self.feature_type == 1:
                self.feature_lock.acquire()
                for card in cards:
                    self.features[card.index] = -1
                self.feature_lock.release()
            else:
                if self.feature_type == 2:
                    feature_index = self.feature_indices[attacker_ix]
                else:
                    if attacker_ix == self.kraudia_ix:
                        feature_index = 0
                    elif attacker_ix == self.next_neighbour():
                        feature_index = self.orig_deck_size
                    elif attacker_ix == self.prev_neighbour():
                        feature_index = self.prev_neighbour_index
                    else:
                        feature_index = -1
                self.feature_lock.acquire()
                if feature_index < 0:
                    for card in cards:
                        self.features[self.field_index + card.index] = 1
                else:
                    for card in cards:
                        self.features[self.field_index + card.index] = 1
                        self.features[feature_index + card.index] = 0
                self.feature_lock.release()

    def defend(self, to_defend, card):
        """Defend the card to defend with the given card."""
        defender = self.players[self.defender_ix]
        assert card in defender.cards, 'Defender does not have the card'
        assert self.field.on_field_attack(to_defend), ('Card to defend is not '
                'on the field as an attack')
        is_greater = card.num_value > to_defend.num_value
        assert (is_greater and card.num_suit == to_defend.num_suit
                or card.num_suit == self.deck.num_trump_suit), \
                'Card is too low'
        if to_defend.num_suit == self.deck.num_trump_suit:
            assert is_greater, 'Card is too low'
        try:
            defender.defend(to_defend, card)
            self.field.defend(to_defend, card)
        except ValueError:
            return False
        # update features
        if self.only_ais:
            if self.feature_type == 1:
                self.feature_lock.acquire()
                self.features[:, card.index] = -1
                self.feature_lock.release()
            else:
                self.feature_lock.acquire()
                self.features[:, self.field_index + card.index] = 1
                if self.feature_type == 2:
                    for ix in range(self.player_count):
                        self.features[ix, self.feature_indices[ix][
                                self.defender_ix] + card.index] = 0
                else:
                    self.features[self.defender_ix, card.index] = 0
                    self.features[self.prev_neighbour(self.defender_ix),
                            self.orig_deck_size + card.index] = 0
                    self.features[self.next_neighbour(self.defender_ix),
                            self.prev_neighbour_index + card.index] = 0
                self.feature_lock.release()
        elif self.kraudia_ix >= 0:
            if self.feature_type == 1:
                self.feature_lock.acquire()
                self.features[card.index] = -1
                self.feature_lock.release()
            else:
                self.feature_lock.acquire()
                self.features[self.field_index + card.index] = 1
                if self.feature_type == 2:
                    self.features[self.feature_indices[self.defender_ix]
                            + card.index] = 0
                else:
                    if self.defender_ix == self.kraudia_ix:
                        self.features[card.index] = 0
                    elif self.defender_ix == self.next_neighbour():
                        self.features[self.orig_deck_size + card.index] = 0
                    elif self.defender_ix == self.prev_neighbour():
                        self.features[self.prev_neighbour_index
                                + card.index] = 0
                self.feature_lock.release()
        return True

    def push(self, cards):
        """Push the cards to the next player."""
        assert not self.field.defended_pairs, ('Cannot push after '
                'having defended')
        assert not self.exceeds_field(cards,
                self.next_neighbour(self.defender_ix)), ('Number of attack '
                'cards exceeds allowed number') 
        self.players[self.defender_ix].push(cards)
        self.field.push(cards)
        # update features
        if self.only_ais:
            if self.feature_type == 1:
                self.feature_lock.acquire()
                for card in cards:
                    self.features[:, card.index] = -1
                self.feature_lock.release()
            elif self.feature_type == 2:
                self.feature_lock.acquire()
                for card in cards:
                    self.features[:, self.field_index + card.index] = 1
                    for ix in range(self.player_count):
                        self.features[ix, self.feature_indices[ix][
                                self.defender_ix] + card.index] = 0
                self.feature_lock.release()
            else:
                prev_neighbour_ix = self.prev_neighbour(self.defender_ix)
                next_neighbour_ix = self.next_neighbour(self.defender_ix)
                self.feature_lock.acquire()
                for card in cards:
                    self.features[:, self.field_index + card.index] = 1
                    self.features[self.defender_ix, card.index] = 0
                    self.features[prev_neighbour_ix, self.orig_deck_size
                            + card.index] = 0
                    self.features[next_neighbour_ix, self.prev_neighbour_index
                            + card.index] = 0
                self.feature_lock.release()
        elif self.kraudia_ix >= 0:
            if self.feature_type == 1:
                self.feature_lock.acquire()
                for card in cards:
                    self.features[card.index] = -1
                self.feature_lock.release()
            else:
                if self.feature_type == 2:
                    feature_index = self.feature_indices[self.defender_ix]
                else:
                    if self.defender_ix == self.kraudia_ix:
                        feature_index = 0
                    elif self.defender_ix == self.next_neighbour():
                        feature_index = self.orig_deck_size
                    elif self.defender_ix == self.prev_neighbour():
                        feature_index = self.prev_neighbour_index
                    else:
                        feature_index = -1
                self.feature_lock.acquire()
                if feature_index < 0:
                    for card in cards:
                        self.features[self.field_index + card.index] = 1
                else:
                    for card in cards:
                        self.features[self.field_index + card.index] = 1
                        self.features[feature_index + card.index] = 0
                self.feature_lock.release()
        self.update_defender()

    def take(self):
        """Make the defender take all the cards on the field and
        return the amount of cards taken."""
        assert not self.field.is_empty(), 'Field cannot be empty'
        # update features (for undefended suit)
        # TODO still rudimentary
        if self.only_ais:
            self.feature_lock.acquire()
            if self.feature_type == 1:
                self.features[self.prev_neighbour(self.defender_ix),
                        self.orig_deck_size] = \
                        self.field.attack_cards[0].num_suit
            else:
                self.features[self.prev_neighbour(self.defender_ix),
                        self.after_index] = \
                        self.field.attack_cards[0].num_suit
            if len(self.field.attack_cards) > 1:
                attack_suits = [card.num_suit
                        for card in self.field.attack_cards]
                for (attack_card, defense_card) in self.field.defended_pairs:
                    if (attack_card.num_suit != self.deck.num_trump_suit
                            and defense_card.num_suit
                            == self.deck.num_trump_suit
                            and attack_card.num_suit in attack_suits):
                        if self.feature_type == 1:
                            self.features[self.prev_neighbour(
                                    self.defender_ix), self.orig_deck_size] = \
                                    attack_card.num_suit
                        else:
                            self.features[self.prev_neighbour(
                                    self.defender_ix), self.after_index] = \
                                    attack_card.num_suit
                        break            
            self.feature_lock.release()
        elif (self.defender_ix == self.next_neighbour()
                and self.kraudia_ix >= 0):
            if self.feature_type == 1:
                self.feature_lock.acquire()
                self.features[self.orig_deck_size] = \
                        self.field.attack_cards[0].num_suit
            else:
                self.feature_lock.acquire()
                self.features[self.after_index] = \
                        self.field.attack_cards[0].num_suit
            if len(self.field.attack_cards) > 1:
                attack_suits = [card.num_suit
                        for card in self.field.attack_cards]
                for (attack_card, defense_card) in self.field.defended_pairs:
                    if (attack_card.num_suit != self.deck.num_trump_suit
                            and defense_card.num_suit
                            == self.deck.num_trump_suit
                            and attack_card.num_suit in attack_suits):
                        if self.feature_type == 1:
                            self.features[self.orig_deck_size] = \
                                    attack_card.num_suit
                        else:
                            self.features[self.after_index] = \
                                    attack_card.num_suit
                        break
            self.feature_lock.release()
        cards = self.field.take()
        self.players[self.defender_ix].take(cards)
        # update features
        if self.only_ais:
            if self.feature_type == 1:
                self.feature_lock.acquire()
                for ix in range(self.player_count):
                    for card in cards:
                        self.features[ix, card.index] = \
                                self.indices_from[ix][self.defender_ix]
                self.feature_lock.release()
            elif self.feature_type == 2:
                self.feature_lock.acquire()
                for card in cards:
                    self.features[:, self.field_index + card.index] = 0
                    for ix in range(self.player_count):
                        self.features[ix, self.feature_indices[ix][
                                self.defender_ix] + card.index] = 1
                self.feature_lock.release()
            else:
                prev_neighbour_ix = self.prev_neighbour(self.defender_ix)
                next_neighbour_ix = self.next_neighbour(self.defender_ix)
                self.feature_lock.acquire()
                for card in cards:
                    self.features[:, self.field_index + card.index] = 0
                    self.features[self.defender_ix, card.index] = 1
                    self.features[prev_neighbour_ix, self.orig_deck_size
                            + card.index] = 1
                    self.features[next_neighbour_ix, self.prev_neighbour_index
                            + card.index] = 1
                self.feature_lock.release()
        elif self.kraudia_ix >= 0:
            if self.feature_type == 1:
                self.feature_lock.acquire()
                for card in cards:
                    self.features[card.index] = self.indices_from_kraudia[
                            self.defender_ix]
                self.feature_lock.release()
            else:
                if self.feature_type == 2:
                    feature_index = self.feature_indices[self.defender_ix]
                else:
                    if self.defender_ix == self.kraudia_ix:
                        feature_index = 0
                    elif self.defender_ix == self.next_neighbour():
                        feature_index = self.orig_deck_size
                    elif self.defender_ix == self.prev_neighbour():
                        feature_index = self.prev_neighbour_index
                    else:
                        feature_index = -1
                self.feature_lock.acquire()
                if feature_index < 0:
                    for card in cards:
                        self.features[self.field_index + card.index] = 0
                else:
                    for card in cards:
                        self.features[self.field_index + card.index] = 0
                        self.features[feature_index + card.index] = 1
                self.feature_lock.release()
        self.update_defender(2)
        return len(cards)

    def check(self, player_ix):
        """Tell the others that the player does not want to attack or
        defend anymore.
        """
        assert player_ix < self.player_count, 'Player does not exist'
        self.players[player_ix].check()
        if player_ix == self.defender_ix:
            # update features
            if self.only_ais:
                if self.feature_type == 1:
                    self.feature_lock.acquire()
                    self.features[:, self.orig_deck_size + 1] = 1
                    self.feature_lock.release()
                else:
                    self.feature_lock.acquire()
                    self.features[:, self.after_index + 2] = 1
                    self.feature_lock.release()
            elif self.kraudia_ix >= 0:
                if self.feature_type == 1:
                    self.feature_lock.acquire()
                    self.features[self.orig_deck_size + 1] = 1
                    self.feature_lock.release()
                else:
                    self.feature_lock.acquire()
                    self.features[self.after_index + 2] = 1
                    self.feature_lock.release()

    def uncheck(self, player_ix):
        """Reset the flag for checking for the given player.
        
        Should only be executed after an attack has ended, not
        during one.
        """
        assert player_ix < self.player_count, 'Player does not exist'
        self.players[player_ix].uncheck()
        if player_ix == self.defender_ix:
            # update features
            if self.only_ais:
                if self.feature_type == 1:
                    self.feature_lock.acquire()
                    self.features[:, self.orig_deck_size + 1] = 0
                    self.feature_lock.release()
                else:
                    self.feature_lock.acquire()
                    self.features[:, self.after_index + 2] = 0
                    self.feature_lock.release()
            elif self.kraudia_ix >= 0:
                if self.feature_type == 1:
                    self.feature_lock.acquire()
                    self.features[self.orig_deck_size + 1] = 0
                    self.feature_lock.release()
                else:
                    self.feature_lock.acquire()
                    self.features[self.after_index + 2] = 0
                    self.feature_lock.release()

    def draw(self, player_ix):
        """Draw cards for the given player until their hand is filled
        or the deck is empty.
        """
        assert player_ix < self.player_count, 'Player does not exist'
        player = self.players[player_ix]
        amount = self.hand_size - len(player.cards)
        if amount > 0:
            cards = self.deck.take(amount)
            player.take(cards)
            # update features
            if self.only_ais:
                if self.feature_type == 1:
                    self.feature_lock.acquire()
                    self.features[:, self.orig_deck_size + 2] = self.deck.size
                    for card in cards:
                        self.features[player_ix, card.index] = 0
                    if self.deck.size == 0:
                        for ix in range(self.player_count):
                            self.features[ix, self.deck.bottom_trump.index] = \
                                    self.indices_from[ix][player_ix]
                    self.feature_lock.release()
                else:
                    self.feature_lock.acquire()
                    self.features[:, self.after_index + 3] = self.deck.size
                    for card in cards:
                        self.features[player_ix, card.index] = 1
                    if self.deck.size == 0:
                        if self.feature_type == 2:
                            for ix in range(self.player_count):
                                self.features[ix,
                                        self.feature_indices[ix][player_ix]
                                        + self.deck.bottom_trump.index] = 1
                        else:
                            self.features[player_ix,
                                    self.deck.bottom_trump.index] = 1
                            self.features[self.prev_neighbour(player_ix),
                                    self.orig_deck_size
                                    + self.deck.bottom_trump.index] = 1
                            self.features[self.next_neighbour(player_ix),
                                    self.prev_neighbour_index
                                    + self.deck.bottom_trump.index] = 1
                    self.feature_lock.release()
            elif self.kraudia_ix >= 0:
                if self.feature_type == 1:
                    self.feature_lock.acquire()
                    self.features[self.orig_deck_size + 2] = self.deck.size
                else:
                    self.feature_lock.acquire()
                    self.features[self.after_index + 3] = self.deck.size
                if player_ix == self.kraudia_ix:
                    if self.feature_type == 1:
                        for card in cards:
                            self.features[card.index] = 0
                    else:
                        for card in cards:
                            self.features[card.index] = 1
                elif self.deck.size == 0:
                    if self.feature_type == 1:
                        self.features[self.deck.bottom_trump.index] = \
                                self.indices_from_kraudia[player_ix]
                    elif self.feature_type == 2:
                        self.features[self.feature_indices[player_ix]
                                + self.deck.bottom_trump.index] = 1
                    else:
                        if player_ix == self.next_neighbour():
                            self.features[self.orig_deck_size
                                    + self.deck.bottom_trump.index] = 1
                        elif player_ix == self.prev_neighbour():
                            self.features[self.prev_neighbour_index
                                    + self.deck.bottom_trump.index] = 1
                self.feature_lock.release()

    def clear_field(self):
        """Clear the field from cards and update the features."""
        cards = self.field.take()
        # update features
        if self.only_ais:
            if self.feature_type == 1:
                self.feature_lock.acquire()
                for card in cards:
                    self.features[:, card.index] = -2
                self.feature_lock.release()
            else:
                self.feature_lock.acquire()
                self.features[:, self.field_index:self.out_index] = 0
                for card in cards:
                    self.features[:, self.out_index + card.index] = 1
                self.feature_lock.release()
        elif self.kraudia_ix >= 0:
            if self.feature_type == 1:
                self.feature_lock.acquire()
                for card in cards:
                    self.features[card.index] = -2
                self.feature_lock.release()
            else:
                self.feature_lock.acquire()
                self.features[self.field_index:self.out_index] = 0
                for card in cards:
                    self.features[self.out_index + card.index] = 1
                self.feature_lock.release()

    def attack_ended(self):
        """Test whether an attack is over because the maximum allowed
        number of attack cards has been placed and defended or because
        all attackers and the defender have checked.
        """
        defender = self.players[self.defender_ix]
        return (not defender.cards
                or len(self.field.defended_pairs) == self.hand_size
                or self.players[self.prev_neighbour(self.defender_ix)].checks
                and self.players[self.next_neighbour(self.defender_ix)].checks
                and defender.checks)

    def exceeds_field(self, cards, player_ix=None):
        """Return whether the number of cards on the field would
        exceed the maximum allowed number of attack cards if the given
        cards were played when the player with the given
        index defends.

        If no index is given, return whether the number of cards
        would exceed the maximum allowed number of cards in general.
        """
        count = (len(self.field.attack_cards)
                + len(self.field.defended_pairs) + len(cards))
        if player_ix is None:
            return count > self.hand_size
        else:
            return count > min(len(self.players[player_ix].cards),
                    self.hand_size)

    def get_actions(self, player_ix=None):
        """Return a list of possible actions for the current game
        state for the given player index.

        If no index is given, kraudia_ix is used. The actions for
        checking and waiting are left out.

        An action is a tuple consisting of:
        - action types attack (0), defend (1), push (2), check (3)
          and wait (4)
        - numerical value of the card to play (-1 if redundant)
        - numerical suit of the card to play (-1 if redundant)
        - if defending, numerical value of the card to defend (else -1)
        - if defending, numerical suit of the card to defend (else -1)
        """
        if player_ix is None:
            player_ix = self.kraudia_ix
        assert player_ix < self.player_count, 'Player does not exist'
        actions = []
        player = self.players[player_ix]
        pushed = 0
        if player_ix == self.defender_ix:
            # actions as defender
            for to_defend in self.field.attack_cards:
                for card in player.cards:
                    is_greater = card.num_value > to_defend.num_value
                    if (is_greater and card.num_suit == to_defend.num_suit
                            or card.num_suit == self.deck.num_trump_suit):
                        if to_defend.num_suit == self.deck.num_trump_suit:
                            if is_greater:
                                actions.append(
                                        self.defend_action(card, to_defend))
                        else:
                            actions.append(self.defend_action(card, to_defend))
                    if (pushed < 2 and card.num_value == to_defend.num_value
                            and not self.field.defended_pairs
                            and not self.exceeds_field([None],
                                    self.next_neighbour(player_ix))): 
                        actions.append(self.push_action(card))
                        if pushed == 0:
                            pushed = 1
                if pushed == 1:
                    pushed = 2
        else:
            is_first_attacker = player_ix == self.prev_neighbour(
                    self.defender_ix)
            if (is_first_attacker
                    or player_ix == self.next_neighbour(self.defender_ix)):
                # actions as first attacker
                if self.field.is_empty() and is_first_attacker:
                    for card in player.cards:
                        actions.append(self.attack_action(card))
                    return actions
                # actions as attacker
                if not self.exceeds_field([None], self.defender_ix):
                    for field_card in (self.field.attack_cards
                            + list(chain.from_iterable(
                            self.field.defended_pairs))):
                        for card in player.cards:
                            if card.num_value == field_card.num_value:
                                actions.append(self.attack_action(card))
            else:
                return []
        return actions

    def attack_action(self, card):
        """Return an action tuple for attacking with the given card."""
        return (0, card.num_value, card.num_suit, -1, -1)

    def defend_action(self, card, to_defend):
        """Return an action tuple for defending the card to defend
        with the given card.
        """
        return (1, card.num_value, card.num_suit, to_defend.num_value,
                to_defend.num_suit)

    def push_action(self, card):
        """Return an action tuple for pushing with the given card."""
        return (2, card.num_value, card.num_suit, -1, -1)

    def check_action(self):
        """Return an action tuple for checking."""
        return (3, -1, -1, -1, -1)

    def wait_action(self):
        """Return an action tuple for waiting."""
        return (4, -1, -1, -1, -1)

    def active_player_indices(self):
        """Return a list of the indices of both attackers and
        the defender.

        Return a list of the indices of the attacker and defender if
        only two players are left.
        """
        if len(self.players) > 2:
            return [self.prev_neighbour(self.defender_ix), self.defender_ix,
                    self.next_neighbour(self.defender_ix)]
        else:
            return [self.prev_neighbour(self.defender_ix), self.defender_ix]

    def prev_neighbour(self, player_ix=None):
        """Return the index of the player coming before the player of
        the given index.

        If no index is given, Kraudia's index is used.
        """
        if player_ix is None:
            player_ix = self.kraudia_ix
        assert player_ix < self.player_count, 'Player does not exist'
        if player_ix == 0:
            return self.player_count - 1
        else:
            return player_ix - 1

    def next_neighbour(self, player_ix=None):
        """Return the index of the player coming after the player of
        the given index.

        If no index is given, Kraudia's index is used.
        """
        if player_ix is None:
            player_ix = self.kraudia_ix
        assert player_ix < self.player_count, 'Player does not exist'
        if player_ix == self.player_count - 1:
            return 0
        else:
            return player_ix + 1

    def index_from(self, player_ix, from_ix=None):
        """Return how far the player at the given index' position is
        from the other index in clockwise direction.

        For example, if from_ix is 2 and player_ix is 5, then return 3
        (with appropriate wrapping). If from_ix is not given,
        use Kraudia's index.
        """
        assert player_ix < self.player_count, 'Player does not exist'
        if from_ix is None:
            from_ix = self.kraudia_ix 
        return (player_ix - from_ix) % self.player_count

    def calculate_indices_from(self, player_ix=None):
        """Return a list of indices expressing how far away those
        players are from the given player index.

        If no index is given, use Kraudia's.
        """
        if player_ix is None:
            player_ix = self.kraudia_ix
        return [self.index_from(x, player_ix)
                for x in range(self.player_count)]

    def calculate_feature_indices(self, only_neighbours=False):
        """Calculate where each player's card features start."""
        if only_neighbours:
            if self.only_ais:
                self.feature_indices = [[ix * self.orig_deck_size
                        for ix in player_indices]
                        for player_indices in self.indices_from]
            else:
                self.feature_indices = [ix * self.orig_deck_size
                        for ix in self.indices_from_kraudia]
        else:
            if self.only_ais:
                self.feature_indices = [[ix * self.orig_deck_size
                        for ix in player_indices]
                        for player_indices in self.indices_from]
            else:
                self.feature_indices = [ix * self.orig_deck_size
                        for ix in self.indices_from_kraudia]

    def update_defender(self, count=1):
        """Increase defender index by count (with wrapping)."""
        for i in range(count):
            self.defender_ix += 1
            if self.defender_ix == self.player_count:
                self.defender_ix = 0

    def sub_neighbour_card(self, card):
        """Subtract one from the feature belonging to the given card's
        value in the neighbours' hands.

        Clips to 0.
        """
        self.features[card.num_value] = max(0,
                self.features[card.num_value] - 1)

    def hand_means(self, player_ix):
        """Return the average value of the given player's cards
        except trump and the average value of the trump cards.
        """
        value_avg = 0
        trump_value_avg = 0
        count = 0
        trump_count = 0
        for card in self.players[player_ix].cards:
            if card.num_suit != self.deck.num_trump_suit:
                value_avg += card.num_value
                count += 1
            else:
                trump_value_avg += card.num_value
                trump_count += 1
        if count > 0:
            value_avg /= float(count)
        if trump_count > 0:
            trump_value_avg /= float(trump_count)
        return value_avg, trump_value_avg, trump_count

    def is_winner(self, player_ix):
        """Return whether a player has no cards left and the deck
        is empty.
        """
        return not self.players[player_ix].cards and self.deck.size == 0

    def remove_player(self, player_ix):
        """Remove the player from the game and return true if only one
        player is left.
        """
        player = self.players[player_ix]
        self.players.remove(player)
        self.player_count -= 1
        if player_ix < self.defender_ix:
            self.defender_ix -= 1
        elif self.defender_ix == self.player_count:
            self.defender_ix = 0
        if player_ix < self.kraudia_ix:
            self.kraudia_ix -= 1
        elif player_ix == self.kraudia_ix:
            self.kraudia_ix = -1
            return self.ended()
        # update features
        if self.only_ais:
            del self.indices_from[player_ix]
            # removed player index from other indices
            removed_from = [self.indices_from[ix][player_ix]
                    for ix in range(self.player_count)]
            self.indices_from = [self.calculate_indices_from(ix)
                    for ix in range(self.player_count)]
            self.feature_lock.acquire()
            if self.feature_type == 3:
                old_features = self.features[player_ix,
                        self.orig_deck_size:self.field_index].copy()
            self.features = np.delete(self.features, player_ix, 0)
            if self.feature_type == 1:
                for ix in range(self.player_count):
                    if removed_from[ix] == 1:
                        self.features[ix, self.orig_deck_size] = -1
                    self.features[ix, np.where(self.features[ix,
                            :self.orig_deck_size] > removed_from[ix])] -= 1
            elif self.feature_type == 2:
                del self.feature_indices[player_ix]
                for ix in range(self.player_count):
                    if removed_from[ix] == 1:
                        self.features[ix, self.after_index] = -1
                    old_ix = self.feature_indices[ix][player_ix]
                    if removed_from[ix] == self.player_count:
                        self.features[ix, old_ix:self.field_index] = 0
                    else:
                        if player_ix == self.player_count:
                            start_ix = self.feature_indices[ix][0]
                        else:
                            start_ix = self.feature_indices[ix][player_ix + 1]
                        to_be_moved = self.features[ix,
                                start_ix:self.field_index].copy()
                        self.features[ix, old_ix:self.field_index] = 0
                        self.features[ix, old_ix:self.field_index
                                - self.orig_deck_size] = to_be_moved
                self.calculate_feature_indices()
            else:
                for ix in range(self.player_count):
                    if removed_from[ix] == 1:
                        self.features[ix, self.after_index] = -1
                        self.features[ix,
                                self.orig_deck_size:self.prev_neighbour_index
                                ] = old_features[:self.orig_deck_size]
                    elif removed_from[ix] == -1:
                        self.features[ix,
                                self.prev_neighbour_index:self.field_index] = \
                                old_features[self.orig_deck_size:]
            self.feature_lock.release()
        elif self.kraudia_ix >= 0:
            removed_from_kraudia = self.indices_from_kraudia[player_ix]
            self.indices_from_kraudia = self.calculate_indices_from()
            self.feature_lock.acquire()
            if self.feature_type == 1:
                if removed_from_kraudia == 1:
                    self.features[self.orig_deck_size] = -1
                self.features[np.where(self.features[:self.orig_deck_size]
                        > removed_from_kraudia)] -= 1
            elif self.feature_type == 2:
                if removed_from_kraudia == 1:
                    self.features[self.after_index] = -1
                old_ix = self.feature_indices[player_ix]
                if removed_from_kraudia == self.player_count:
                    self.features[old_ix:self.field_index] = 0
                else:
                    if player_ix == self.player_count:
                        start_ix = self.feature_indices[0]
                    else:
                        start_ix = self.feature_indices[player_ix + 1]
                    to_be_moved = self.features[
                            start_ix:self.field_index].copy()
                    self.features[old_ix:self.field_index] = 0
                    self.features[old_ix:self.field_index
                            - self.orig_deck_size] = to_be_moved
                self.calculate_feature_indices()
            else:
                if removed_from_kraudia == 1:
                    self.features[self.after_index] = -1
                    self.features[
                            self.orig_deck_size:self.prev_neighbour_index] = 0
                elif removed_from_kraudia == -1:
                    self.features[
                            self.prev_neighbour_index:self.field_index] = 0
            self.feature_lock.release()
        return self.ended()

    def will_end(self):
        """Return whether two or less players are left."""
        return self.player_count <= 2

    def ended(self):
        """Return whether no player aside from one is left."""
        return self.player_count <= 1
