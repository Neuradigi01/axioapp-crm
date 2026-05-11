import 'package:flutter/material.dart';

/// Lightweight value object for country dropdown items.
class CountryItem {
  const CountryItem({required this.id, required this.name});

  final int id;
  final String name;

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is CountryItem &&
          runtimeType == other.runtimeType &&
          id == other.id;

  @override
  int get hashCode => id.hashCode;

  @override
  String toString() => name;
}

/// Lightweight value object for state dropdown items.
class StateItem {
  const StateItem({required this.id, required this.name});

  final int id;
  final String name;

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is StateItem &&
          runtimeType == other.runtimeType &&
          id == other.id;

  @override
  int get hashCode => id.hashCode;

  @override
  String toString() => name;
}

/// A paired Country + State dropdown picker.
///
/// - Country dropdown with search/filter support.
/// - State dropdown updates when the selected country changes.
/// - Parent supplies data via [countries] and [states] props.
/// - Parent is notified via [onCountryChanged] to load states for the
///   selected country.
class CountryStatePicker extends StatefulWidget {
  const CountryStatePicker({
    super.key,
    required this.countries,
    required this.states,
    this.selectedCountry,
    this.selectedState,
    required this.onCountryChanged,
    required this.onStateChanged,
    this.isLoadingCountries = false,
    this.isLoadingStates = false,
    this.enabled = true,
    this.countryValidator,
    this.stateValidator,
  });

  /// List of available countries.
  final List<CountryItem> countries;

  /// List of states for the currently selected country.
  final List<StateItem> states;

  /// Currently selected country.
  final CountryItem? selectedCountry;

  /// Currently selected state.
  final StateItem? selectedState;

  /// Called when the user selects a country.
  final ValueChanged<CountryItem?> onCountryChanged;

  /// Called when the user selects a state.
  final ValueChanged<StateItem?> onStateChanged;

  /// Whether countries are currently loading.
  final bool isLoadingCountries;

  /// Whether states are currently loading.
  final bool isLoadingStates;

  /// Whether the dropdowns are enabled.
  final bool enabled;

  /// Optional validator for country field.
  final String? Function(CountryItem?)? countryValidator;

  /// Optional validator for state field.
  final String? Function(StateItem?)? stateValidator;

  @override
  State<CountryStatePicker> createState() => _CountryStatePickerState();
}

class _CountryStatePickerState extends State<CountryStatePicker> {
  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _buildCountryDropdown(context),
        const SizedBox(height: 16),
        _buildStateDropdown(context),
      ],
    );
  }

  Widget _buildCountryDropdown(BuildContext context) {
    final theme = Theme.of(context);

    if (widget.isLoadingCountries) {
      return InputDecorator(
        decoration: const InputDecoration(
          labelText: 'Country',
          prefixIcon: Icon(Icons.public),
        ),
        child: Row(
          children: [
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: theme.colorScheme.primary,
              ),
            ),
            const SizedBox(width: 12),
            Text(
              'Loading countries...',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
      );
    }

    return DropdownButtonFormField<CountryItem>(
      initialValue: widget.selectedCountry,
      isExpanded: true,
      decoration: const InputDecoration(
        labelText: 'Country',
        prefixIcon: Icon(Icons.public),
      ),
      items: widget.countries
          .map(
            (country) => DropdownMenuItem<CountryItem>(
              value: country,
              child: Text(country.name, overflow: TextOverflow.ellipsis),
            ),
          )
          .toList(),
      onChanged: widget.enabled
          ? (country) {
              widget.onCountryChanged(country);
            }
          : null,
      validator: widget.countryValidator,
      selectedItemBuilder: (context) {
        return widget.countries.map((country) {
          return Text(country.name, overflow: TextOverflow.ellipsis);
        }).toList();
      },
    );
  }

  Widget _buildStateDropdown(BuildContext context) {
    final theme = Theme.of(context);
    final bool hasCountry = widget.selectedCountry != null;

    if (widget.isLoadingStates) {
      return InputDecorator(
        decoration: const InputDecoration(
          labelText: 'State',
          prefixIcon: Icon(Icons.location_city),
        ),
        child: Row(
          children: [
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: theme.colorScheme.primary,
              ),
            ),
            const SizedBox(width: 12),
            Text(
              'Loading states...',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
      );
    }

    return DropdownButtonFormField<StateItem>(
      initialValue: widget.selectedState,
      isExpanded: true,
      decoration: const InputDecoration(
        labelText: 'State',
        prefixIcon: Icon(Icons.location_city),
      ),
      items: widget.states
          .map(
            (state) => DropdownMenuItem<StateItem>(
              value: state,
              child: Text(state.name, overflow: TextOverflow.ellipsis),
            ),
          )
          .toList(),
      onChanged: widget.enabled && hasCountry
          ? (state) {
              widget.onStateChanged(state);
            }
          : null,
      validator: widget.stateValidator,
      hint: Text(
        hasCountry ? 'Select state' : 'Select a country first',
        style: theme.textTheme.bodyMedium?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
        ),
      ),
      selectedItemBuilder: (context) {
        return widget.states.map((state) {
          return Text(state.name, overflow: TextOverflow.ellipsis);
        }).toList();
      },
    );
  }
}

/// A searchable country dropdown that uses [Autocomplete] for filtering.
///
/// Use this instead of [CountryStatePicker] when you need search/filter
/// on the country field specifically.
class SearchableCountryField extends StatelessWidget {
  const SearchableCountryField({
    super.key,
    required this.countries,
    this.selectedCountry,
    required this.onSelected,
    this.isLoading = false,
    this.enabled = true,
    this.validator,
  });

  final List<CountryItem> countries;
  final CountryItem? selectedCountry;
  final ValueChanged<CountryItem> onSelected;
  final bool isLoading;
  final bool enabled;
  final String? Function(String?)? validator;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    if (isLoading) {
      return InputDecorator(
        decoration: const InputDecoration(
          labelText: 'Country',
          prefixIcon: Icon(Icons.public),
        ),
        child: Row(
          children: [
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: theme.colorScheme.primary,
              ),
            ),
            const SizedBox(width: 12),
            Text(
              'Loading countries...',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
      );
    }

    return Autocomplete<CountryItem>(
      initialValue: selectedCountry != null
          ? TextEditingValue(text: selectedCountry!.name)
          : null,
      optionsBuilder: (textEditingValue) {
        if (textEditingValue.text.isEmpty) return countries;
        final query = textEditingValue.text.toLowerCase();
        return countries.where(
          (c) => c.name.toLowerCase().contains(query),
        );
      },
      displayStringForOption: (country) => country.name,
      onSelected: onSelected,
      fieldViewBuilder: (context, controller, focusNode, onSubmitted) {
        return TextFormField(
          controller: controller,
          focusNode: focusNode,
          enabled: enabled,
          validator: validator,
          decoration: const InputDecoration(
            labelText: 'Country',
            prefixIcon: Icon(Icons.public),
            suffixIcon: Icon(Icons.arrow_drop_down),
          ),
          onFieldSubmitted: (_) => onSubmitted(),
        );
      },
      optionsViewBuilder: (context, onSelected, options) {
        return Align(
          alignment: Alignment.topLeft,
          child: Material(
            elevation: 4,
            borderRadius: BorderRadius.circular(8),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 240),
              child: ListView.builder(
                padding: EdgeInsets.zero,
                shrinkWrap: true,
                itemCount: options.length,
                itemBuilder: (context, index) {
                  final option = options.elementAt(index);
                  return ListTile(
                    title: Text(option.name),
                    onTap: () => onSelected(option),
                  );
                },
              ),
            ),
          ),
        );
      },
    );
  }
}
