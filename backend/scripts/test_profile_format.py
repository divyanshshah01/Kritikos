"""
Test whether the generated Profile format complies with OASIS requirements
éªŒè¯: 
1. Twitter Profileç”ŸæˆCSVFormat
2. Reddit Profileç”ŸæˆJSONDetailed format
"""

import os
import sys
import json
import csv
import tempfile

# æ·»åŠ é¡¹ç›®è·¯å¾„
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.oasis_profile_generator import OasisProfileGenerator, OasisAgentProfile


def test_profile_formats():
    """æµ‹TestProfileFormat"""
    print("=" * 60)
    print("OASIS ProfileFormatæµ‹Test")
    print("=" * 60)
    
    # Createæµ‹TestProfileæ•°æ®
    test_profiles = [
        OasisAgentProfile(
            user_id=0,
            user_name="test_user_123",
            name="Test User",
            bio="A test user for validation",
            persona="Test User is an enthusiastic participant in social discussions.",
            karma=1500,
            friend_count=100,
            follower_count=200,
            statuses_count=500,
            age=25,
            gender="male",
            mbti="INTJ",
            country="China",
            profession="Student",
            interested_topics=["Technology", "Education"],
            source_entity_uuid="test-uuid-123",
            source_entity_type="Student",
        ),
        OasisAgentProfile(
            user_id=1,
            user_name="org_official_456",
            name="Official Organization",
            bio="Official account for Organization",
            persona="This is an official institutional account that communicates official positions.",
            karma=5000,
            friend_count=50,
            follower_count=10000,
            statuses_count=200,
            profession="Organization",
            interested_topics=["Public Policy", "Announcements"],
            source_entity_uuid="test-uuid-456",
            source_entity_type="University",
        ),
    ]
    
    generator = OasisProfileGenerator.__new__(OasisProfileGenerator)
    
    # ä½¿Useä¸´ hourç›®å½•
    with tempfile.TemporaryDirectory() as temp_dir:
        twitter_path = os.path.join(temp_dir, "twitter_profiles.csv")
        reddit_path = os.path.join(temp_dir, "reddit_profiles.json")
        
        # æµ‹TestTwitter CSVFormat
        print("\n1. æµ‹TestTwitter Profile (CSVFormat)")
        print("-" * 40)
        generator._save_twitter_csv(test_profiles, twitter_path)
        
        # è¯»å–å¹¶éªŒè¯CSV
        with open(twitter_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
        print(f"   æ–‡ä»¶: {twitter_path}")
        print(f"   è¡Œæ•°: {len(rows)}")
        print(f"   è¡¨å¤´: {list(rows[0].keys())}")
        print(f"\n   Exampleä¾‹æ•°æ® (ç¬¬1è¡Œ):")
        for key, value in rows[0].items():
            print(f"     {key}: {value}")
        
        # éªŒè¯å¿…éœ€å­—Segment
        required_twitter_fields = ['user_id', 'user_name', 'name', 'bio', 
                                   'friend_count', 'follower_count', 'statuses_count', 'created_at']
        missing = set(required_twitter_fields) - set(rows[0].keys())
        if missing:
            print(f"\n   [é”™è¯¯] ç¼ºå°‘å­—Segment: {missing}")
        else:
            print(f"\n   [é€šè¿‡] æ‰€haså¿…éœ€å­—Segmentéƒ½å­˜åœ¨")
        
        # æµ‹TestReddit JSONFormat
        print("\n2. æµ‹TestReddit Profile (JSONDetailed format)")
        print("-" * 40)
        generator._save_reddit_json(test_profiles, reddit_path)
        
        # è¯»å–å¹¶éªŒè¯JSON
        with open(reddit_path, 'r', encoding='utf-8') as f:
            reddit_data = json.load(f)
        
        print(f"   æ–‡ä»¶: {reddit_path}")
        print(f"    itemsç›®æ•°: {len(reddit_data)}")
        print(f"   å­—Segment: {list(reddit_data[0].keys())}")
        print(f"\n   Exampleä¾‹æ•°æ® (ç¬¬1 items):")
        print(json.dumps(reddit_data[0], ensure_ascii=False, indent=4))
        
        # éªŒè¯Detailed formatå­—Segment
        required_reddit_fields = ['realname', 'username', 'bio', 'persona']
        optional_reddit_fields = ['age', 'gender', 'mbti', 'country', 'profession', 'interested_topics']
        
        missing = set(required_reddit_fields) - set(reddit_data[0].keys())
        if missing:
            print(f"\n   [é”™è¯¯] ç¼ºå°‘å¿…éœ€å­—Segment: {missing}")
        else:
            print(f"\n   [é€šè¿‡] æ‰€haså¿…éœ€å­—Segmentéƒ½å­˜åœ¨")
        
        present_optional = set(optional_reddit_fields) & set(reddit_data[0].keys())
        print(f"   [ä¿¡æ¯] å¯é€‰å­—Segment: {present_optional}")
    
    print("\n" + "=" * 60)
    print("æµ‹Testå®Œæˆ!")
    print("=" * 60)


def show_expected_formats():
    """Display OASIS expected format"""
    print("\n" + "=" * 60)
    print("OASIS æœŸæœ›çš„ProfileFormatå‚è€ƒ")
    print("=" * 60)
    
    print("\n1. Twitter Profile (CSVFormat)")
    print("-" * 40)
    twitter_example = """user_id,user_name,name,bio,friend_count,follower_count,statuses_count,created_at
0,user0,User Zero,I am user zero with interests in technology.,100,150,500,2023-01-01
1,user1,User One,Tech enthusiast and coffee lover.,200,250,1000,2023-01-02"""
    print(twitter_example)
    
    print("\n2. Reddit Profile (JSONDetailed format)")
    print("-" * 40)
    reddit_example = [
        {
            "realname": "James Miller",
            "username": "millerhospitality",
            "bio": "Passionate about hospitality & tourism.",
            "persona": "James is a seasoned professional in the Hospitality & Tourism industry...",
            "age": 40,
            "gender": "male",
            "mbti": "ESTJ",
            "country": "UK",
            "profession": "Hospitality & Tourism",
            "interested_topics": ["Economics", "Business"]
        }
    ]
    print(json.dumps(reddit_example, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    test_profile_formats()
    show_expected_formats()


