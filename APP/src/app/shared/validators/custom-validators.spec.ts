import { FormControl, FormGroup } from '@angular/forms';

import {
  REASON,
  emailValidator,
  matchFieldValidator,
  nameValidator,
  passwordStrengthValidator,
  phoneValidator,
  urlValidator,
} from './custom-validators';

/**
 * Unit coverage for the shared frontend validators
 * (tasks/application-updates/ Step 1).
 *
 * Each validator is exercised against an accept list, a reject list,
 * and the empty-value short-circuit. Empty values return `null` — the
 * "required" concern belongs to `Validators.required`, not these
 * format checks.
 *
 * Backend mirror lives in `api/src/app/shared/validators.py`; a
 * regex-sync guard test on the Python side asserts the two produce
 * identical behaviour on a shared matrix.
 */

function ctl(value: unknown): FormControl {
  return new FormControl(value);
}

describe('shared validators', () => {
  describe('nameValidator', () => {
    it('returns null for empty values', () => {
      expect(nameValidator(ctl(''))).toBeNull();
      expect(nameValidator(ctl(null))).toBeNull();
      expect(nameValidator(ctl(undefined))).toBeNull();
    });

    it('accepts real names', () => {
      for (const v of ['John', 'Mary-Jane', "O'Neil", 'Jean-Luc Picard', 'Renée', 'Dr. Smith']) {
        expect(nameValidator(ctl(v)))
          .withContext(v)
          .toBeNull();
      }
    });

    it('rejects digits, emoji, symbols with "disallowed characters" reason', () => {
      for (const v of ['John123', '😀', '<script>', 'A@B']) {
        expect(nameValidator(ctl(v)))
          .withContext(v)
          .toEqual({ nameInvalid: REASON.invalidName });
      }
    });

    it('rejects too-short names with a length-specific reason', () => {
      // 'J' is a valid character but fails the 2-char minimum; the
      // error must call that out instead of blaming the character set.
      for (const v of ['J', 'a', '  ']) {
        expect(nameValidator(ctl(v)))
          .withContext(v)
          .toEqual({ nameInvalid: REASON.nameTooShort });
      }
    });

    it('rejects too-long names with a length-specific reason', () => {
      const v = 'A'.repeat(101);
      expect(nameValidator(ctl(v))).toEqual({ nameInvalid: REASON.nameTooLong });
    });
  });

  describe('emailValidator', () => {
    it('returns null for empty values', () => {
      expect(emailValidator(ctl(''))).toBeNull();
      expect(emailValidator(ctl(null))).toBeNull();
    });

    it('accepts valid addresses', () => {
      for (const v of ['user@example.com', 'user+tag@ex.co', 'a.b@c.d']) {
        expect(emailValidator(ctl(v)))
          .withContext(v)
          .toBeNull();
      }
    });

    it('rejects malformed addresses', () => {
      for (const v of ['test@', '@example.com', 'no-at.com', 'a b@x.com']) {
        expect(emailValidator(ctl(v)))
          .withContext(v)
          .toEqual({ emailInvalid: REASON.invalidEmail });
      }
    });

    it('rejects addresses over 254 chars', () => {
      const long = 'a'.repeat(250) + '@x.co';
      expect(emailValidator(ctl(long))).toEqual({
        emailInvalid: REASON.invalidEmail,
      });
    });
  });

  describe('phoneValidator (10-digit Indian mobile)', () => {
    it('returns null for empty values', () => {
      expect(phoneValidator(ctl(''))).toBeNull();
    });

    it('accepts Indian mobile numbers with or without +91', () => {
      for (const v of [
        '9876543210',
        '+91 98765 43210',
        '91-9876543210',
        '+919876543210',
        '(987) 654-3210',
        '6234567890',
        '7234567890',
        '8234567890',
      ]) {
        expect(phoneValidator(ctl(v)))
          .withContext(v)
          .toBeNull();
      }
    });

    it('rejects non-Indian, landline, or malformed numbers', () => {
      for (const v of [
        'abc',
        '1234567',
        '5234567890', // starts with 5
        '0987654321', // leading zero
        '12345678901', // 11 digits
        '+1 415 555 0132', // US
        '020-79460958', // Delhi landline
      ]) {
        expect(phoneValidator(ctl(v)))
          .withContext(v)
          .toEqual({ phoneInvalid: REASON.invalidPhone });
      }
    });
  });

  describe('passwordStrengthValidator', () => {
    it('returns null for empty values', () => {
      expect(passwordStrengthValidator(ctl(''))).toBeNull();
    });

    it('accepts strong passwords', () => {
      for (const v of ['Passw0rd!', 'Xy9!zzzz', 'Longer#One1']) {
        expect(passwordStrengthValidator(ctl(v)))
          .withContext(v)
          .toBeNull();
      }
    });

    it('rejects weak passwords', () => {
      for (const v of [
        'password',
        'PASSWORD1!',
        'passw0rd!',
        'Password!',
        'Password1',
        'Pw1!',
        'a'.repeat(129) + 'A1!',
      ]) {
        expect(passwordStrengthValidator(ctl(v)))
          .withContext(v)
          .toEqual({ passwordWeak: REASON.weakPassword });
      }
    });
  });

  describe('urlValidator', () => {
    it('returns null for empty values', () => {
      expect(urlValidator(ctl(''))).toBeNull();
    });

    it('accepts http and https URLs', () => {
      for (const v of ['https://example.com', 'http://x.co/y?z=1']) {
        expect(urlValidator(ctl(v)))
          .withContext(v)
          .toBeNull();
      }
    });

    it('rejects bare hosts and non-http schemes', () => {
      for (const v of ['example.com', 'ftp://x.co', 'https://', '   ']) {
        expect(urlValidator(ctl(v)))
          .withContext(v)
          .toEqual({ urlInvalid: REASON.invalidUrl });
      }
    });
  });

  describe('matchFieldValidator (regression)', () => {
    it('fires when values differ in the same group', () => {
      const group = new FormGroup({
        password: new FormControl('one'),
        confirm: new FormControl('two', [matchFieldValidator('password')]),
      });
      expect(group.controls.confirm.errors).toEqual({ passwordMismatch: true });
    });

    it('clears when values match', () => {
      const group = new FormGroup({
        password: new FormControl('one'),
        confirm: new FormControl('one', [matchFieldValidator('password')]),
      });
      expect(group.controls.confirm.errors).toBeNull();
    });
  });
});
